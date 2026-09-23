"""Pilot phase: pick single-cell sms pilots, feed results into the posterior."""

MIN_CELL_SIZE = 300
ROUND1_PILOTS = 10
ROUND1_N = 150
ROUND2_N = 200
PILOT_CHANNEL = "sms"


class Explorer:
    def __init__(self, env, cells, posterior):
        self.env = env
        self.cells = cells
        self.post = posterior
        self.log = []  # our own record of every pilot incl. filters

    def candidates(self):
        targets = list(self.env.tariffs["tariff_plan_code"])
        out = []
        for cell, info in self.cells.items():
            if info["size"] < MIN_CELL_SIZE:
                continue
            value = info["size"] * info["arpu"]
            for target in targets:
                if target == cell[0]:
                    continue
                out.append((self.post.ucb(cell, target) * value, cell, target))
        out.sort(key=lambda x: x[0], reverse=True)
        return [(cell, target) for _, cell, target in out]

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

        # Round 2: re-pilot close calls (mean > 0 but LCB < 0) while resources allow.
        tested = {(p["current_tariff"], p["arpu_segment"], p["target_tariff"]) for p in self.log}
        while self._can_pilot(ROUND2_N):
            close = []
            for tariff, segment, target in tested:
                cell = (tariff, segment)
                mean, sd = self.post.get(cell, target)
                if mean > 0 and mean - sd < 0:
                    info = self.cells[cell]
                    close.append((self.post.ucb(cell, target) * info["size"] * info["arpu"],
                                  cell, target))
            if not close:
                break
            close.sort(key=lambda x: x[0], reverse=True)
            _, cell, target = close[0]
            if self.pilot(cell, target, ROUND2_N) is None:
                break
        return self.log
