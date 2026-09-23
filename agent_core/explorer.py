"""Pilot phase: pick single-cell sms pilots, feed results into the posterior."""

from .llm_advisor import arm_id
from .planner import FINAL_K
from .priors import get_prior

MIN_CELL_SIZE = 300
ROUND1_PILOTS = 10
ROUND1_PER_CELL = 2
ROUND1_N = 150
ROUND2_N = 200
MAX_PILOTS_PER_ARM = 2  # screen + one confirmation; no re-piloting until lucky
# Adaptive stop: skip round 2 when no arm looks positive on both posterior and pilots
# alone; end round 2 as soon as one arm passes the launch gate. Off: on stress_eval it
# kept 40/50 but did not improve the worst run (-227,816, lost in round-1 pilots).
ADAPTIVE_STOP = False
PILOT_CHANNEL = "sms"
# The effect ratio depends only on the (tariff, arpu_segment) cell, so a pilot on any
# data/call slice of the cell observes the same ratio. Pilot on the slice with the lowest
# mean predicted ARPU (enough customers for n): same signal, smaller loss if negative.
CHEAP_SLICE_PILOTS = True
SLICE_COLUMNS = ("data_segment", "call_segment")


class Explorer:
    def __init__(self, env, cells, posterior, advisor=None):
        self.env = env
        self.cells = cells
        self.post = posterior
        self.advisor = advisor
        self.log = []  # our own record of every pilot incl. filters

    def _upsell_targets(self, tariff):
        """Targets priced above `tariff`, nearest first; [] if prices are unknown."""
        if "price_tariff" not in self.env.tariffs.columns:
            return []
        price = dict(zip(self.env.tariffs["tariff_plan_code"], self.env.tariffs["price_tariff"]))
        current = price.get(tariff)
        if current is None:
            return []
        higher = [t for t, p in price.items() if p > current]
        return sorted(higher, key=lambda t: (price[t] - current, t))

    def candidates(self):
        """Round-1 arms: cells by value (size x mean ARPU); per cell the targets with a
        positive prior mean, topped up with the nearest higher-priced tariffs (upsell) when
        the prior has nothing positive to say (e.g. no history table)."""
        targets = list(self.env.tariffs["tariff_plan_code"])
        big = [c for c, info in self.cells.items() if info["size"] >= MIN_CELL_SIZE]
        big.sort(key=lambda c: self.cells[c]["size"] * self.cells[c]["arpu"], reverse=True)
        out = []
        for cell in big:
            positive = [t for t in targets if t != cell[0] and self.post.get(cell, t)[0] > 0]
            ranked = sorted(positive, key=lambda t: self.post.get(cell, t)[0], reverse=True)
            for t in self._upsell_targets(cell[0]):
                if len(ranked) >= ROUND1_PER_CELL:
                    break
                if t not in ranked and self.post.get(cell, t)[0] >= 0:
                    ranked.append(t)
            out.extend((cell, t) for t in ranked[:ROUND1_PER_CELL])
        return out

    def _can_pilot(self, n):
        cost = self.env.channels[PILOT_CHANNEL]["cost_per_contact"]
        return (self.env.pilots_left > 0 and self.env.remaining_contacts >= 10
                and self.env.remaining_budget >= cost * min(n, 10))

    def _cheapest_slice(self, cell, n):
        """{filter_<column>: value} of the lowest-mean-ARPU slice with >= n customers, or {}."""
        profile = self.env.customer_profile
        sub = profile[(profile["current_tariff"] == cell[0])
                      & (profile["arpu_segment"] == cell[1])]
        best = None
        for column in SLICE_COLUMNS:
            g = sub.groupby(column, observed=True)["predicted_arpu"].agg(["size", "mean"])
            for value, row in g[g["size"] >= n].iterrows():
                if best is None or row["mean"] < best[0]:
                    best = (row["mean"], {f"filter_{column}": value})
        return best[1] if best else {}

    def pilot(self, cell, target, n):
        tariff, segment = cell
        slice_filter = self._cheapest_slice(cell, n) if CHEAP_SLICE_PILOTS else {}
        try:
            res = self.env.run_pilot(target_tariff=target, channel=PILOT_CHANNEL,
                                     n_customers=n, filter_current_tariff=tariff,
                                     filter_arpu_segment=segment, **slice_filter)
        except (RuntimeError, ValueError):
            return None
        mult = self.env.channels[PILOT_CHANNEL]["conversion_multiplier"]
        mean, sd = self.post.update(cell, target, res["observed_lift_ratio"],
                                    res["n_customers"], mult)
        self.log.append({
            "current_tariff": tariff, "arpu_segment": segment, "target_tariff": target,
            "slice": slice_filter, "channel": PILOT_CHANNEL, "n": res["n_customers"], "cost": res["cost"],
            "observed_ratio": res["observed_lift_ratio"], "post_mean": mean, "post_sd": sd,
        })
        return res

    def _passes_gate(self, cell, target):
        mean, sd = self.post.get(cell, target)
        return self.post.confirmed_enough(cell, target) and mean - FINAL_K * sd > 0

    def _any_promising(self, tested):
        """Some arm with posterior mean > 0 AND pilot-only mean > 0."""
        for tariff, segment, target in sorted(tested):
            cell = (tariff, segment)
            pilot = self.post.pilot_only(cell, target)
            if self.post.get(cell, target)[0] > 0 and pilot is not None and pilot[0] > 0:
                return True
        return False

    def _open_leaders(self, tested):
        """Arms worth confirming, best first: mean > 0, not capped, not yet through the gate."""
        out = []
        for tariff, segment, target in sorted(tested):
            cell = (tariff, segment)
            mean, sd = self.post.get(cell, target)
            if mean <= 0 or self.post.n_obs.get((cell, target), 0) >= MAX_PILOTS_PER_ARM:
                continue
            if self._passes_gate(cell, target):
                continue
            info = self.cells[cell]
            out.append((mean * info["size"] * info["arpu"], cell, target))
        out.sort(key=lambda x: x[0], reverse=True)
        return out

    def posterior_table(self):
        """Every piloted arm with prior, posterior and evidence, for the LLM advisor."""
        rows = []
        for cell, target in sorted({((p["current_tariff"], p["arpu_segment"]), p["target_tariff"])
                                    for p in self.log}):
            prior_mean, prior_sd = get_prior(cell, target)
            mean, sd = self.post.get(cell, target)
            rows.append({
                "arm": arm_id(cell, target),
                "cell_size": self.cells[cell]["size"], "cell_mean_arpu": round(self.cells[cell]["arpu"], 1),
                "prior_mean": round(prior_mean, 4), "prior_sd": round(prior_sd, 4),
                "base_mean": round(mean, 4), "base_sd": round(sd, 4),
                "pilots": self.post.n_obs.get((cell, target), 0),
                "customers": self.post.n_total.get((cell, target), 0),
                "observed_ratios": [round(p["observed_ratio"], 4) for p in self.log
                                    if (p["current_tariff"], p["arpu_segment"]) == cell
                                    and p["target_tariff"] == target],
            })
        return rows

    def run(self):
        # Round 1: cells by value (size x mean ARPU), targets by prior mean / upsell price.
        for cell, target in self.candidates()[:ROUND1_PILOTS]:
            if not self._can_pilot(ROUND1_N):
                break
            self.pilot(cell, target, ROUND1_N)

        # Round 2: confirm round-1 leaders (mean > 0) until they pass or fail the final gate.
        tested = {(p["current_tariff"], p["arpu_segment"], p["target_tariff"]) for p in self.log}
        if ADAPTIVE_STOP and not self._any_promising(tested):
            return self.log
        priority = {}
        if self.advisor is not None and self.advisor.enabled:
            ours = [(cell, target) for _, cell, target in self._open_leaders(tested)]
            ranked = self.advisor.rank_confirmations(ours, self.posterior_table())
            priority = {arm: i for i, arm in enumerate(ranked)}
        while self._can_pilot(ROUND2_N):
            open_leaders = self._open_leaders(tested)
            if not open_leaders:
                break
            open_leaders.sort(key=lambda x: priority.get((x[1], x[2]), len(priority)))
            _, cell, target = open_leaders[0]
            if self.pilot(cell, target, ROUND2_N) is None:
                break
            if ADAPTIVE_STOP and any(self._passes_gate((t, s), g) for t, s, g in sorted(tested)):
                break
        return self.log
