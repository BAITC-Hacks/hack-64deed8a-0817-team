"""Pilot phase: pick single-cell sms pilots, feed results into the posterior."""

from .planner import FINAL_K

MIN_CELL_SIZE = 300
ROUND1_PILOTS = 10
ROUND1_PER_CELL = 2
ROUND1_N = 150
ROUND2_N = 200
MAX_PILOTS_PER_ARM = 2  # screen + one confirmation; no re-piloting until lucky
PILOT_CHANNEL = "sms"


class Explorer:
    def __init__(self, env, cells, posterior):
        self.env = env
        self.cells = cells
        self.post = posterior
        self.log = []  # our own record of every pilot incl. filters

    def candidates(self):
        """Round-1 arms: cells by value (size x mean ARPU), best targets by prior mean."""
        targets = list(self.env.tariffs["tariff_plan_code"])
        big = [c for c, info in self.cells.items() if info["size"] >= MIN_CELL_SIZE]
        big.sort(key=lambda c: self.cells[c]["size"] * self.cells[c]["arpu"], reverse=True)
        out = []
        for cell in big:
            ranked = sorted((t for t in targets if t != cell[0]),
                            key=lambda t: self.post.get(cell, t)[0], reverse=True)
            out.extend((cell, t) for t in ranked[:ROUND1_PER_CELL])
        return out

    def _can_pilot(self, n):
        cost = self.env.channels[PILOT_CHANNEL]["cost_per_contact"]
        return (self.env.pilots_left > 0 and self.env.remaining_contacts >= 10
                and self.env.remaining_budget >= cost * min(n, 10))

    def pilot(self, cell, target, n):
        tariff, segment = cell
        try:
            res = self.env.run_pilot(target_tariff=target, channel=PILOT_CHANNEL,
                                     n_customers=n, filter_current_tariff=tariff,
                                     filter_arpu_segment=segment)
        except (RuntimeError, ValueError):
            return None
        mult = self.env.channels[PILOT_CHANNEL]["conversion_multiplier"]
        mean, sd = self.post.update(cell, target, res["observed_lift_ratio"],
                                    res["n_customers"], mult)
        self.log.append({
            "current_tariff": tariff, "arpu_segment": segment, "target_tariff": target,
            "channel": PILOT_CHANNEL, "n": res["n_customers"], "cost": res["cost"],
            "observed_ratio": res["observed_lift_ratio"], "post_mean": mean, "post_sd": sd,
        })
        return res

    def run(self):
        # Round 1: top candidates by prior UCB x cell value.
        for cell, target in self.candidates()[:ROUND1_PILOTS]:
            if not self._can_pilot(ROUND1_N):
                break
            self.pilot(cell, target, ROUND1_N)

        # Round 2: confirm round-1 leaders (mean > 0) until they pass or fail the final gate.
        tested = {(p["current_tariff"], p["arpu_segment"], p["target_tariff"]) for p in self.log}
        while self._can_pilot(ROUND2_N):
            open_leaders = []
            for tariff, segment, target in tested:
                cell = (tariff, segment)
                mean, sd = self.post.get(cell, target)
                if mean <= 0 or self.post.n_obs.get((cell, target), 0) >= MAX_PILOTS_PER_ARM:
                    continue
                if self.post.confirmed_enough(cell, target) and mean - FINAL_K * sd > 0:
                    continue
                info = self.cells[cell]
                open_leaders.append((mean * info["size"] * info["arpu"], cell, target))
            if not open_leaders:
                break
            open_leaders.sort(key=lambda x: x[0], reverse=True)
            _, cell, target = open_leaders[0]
            if self.pilot(cell, target, ROUND2_N) is None:
                break
        return self.log
