"""Policy v4: wide screening, winner's-curse re-check, launch every pilot-positive arm.

Pilots: one target per cell (highest prior mean among higher-priced tariffs, never a
downgrade); the top 10 cells by prior x size x mean ARPU get one sms pilot of 150 on the
cheapest slice; then up to 5 pilots of 200 re-check the top 3 arms by observed ratio.
Finals: every arm with pooled pilot estimate > 0 and posterior mean > 0, ranked by
expected total net, channel and size from the planner economics, no overlapping segments.
"""

from .explorer import ROUND1_N, ROUND2_N, Explorer
from .planner import Planner, _best_assignment

V4_ROUND1_PILOTS = 10
V4_RECHECK_ARMS = 3
V4_RECHECK_PILOTS = 5


class ExplorerV4(Explorer):
    def candidates(self):
        """One upsell target per cell (highest prior mean); cells by prior x size x ARPU."""
        scored = []
        eligible = set(self._eligible_cells())
        for cell, info in sorted(self.cells.items()):
            if cell not in eligible:
                continue
            upsell = self._upsell_targets(cell[0])
            if not upsell:
                continue
            target = max(upsell, key=lambda t: (self.post.get(cell, t)[0], -upsell.index(t)))
            prior = self.post.get(cell, target)[0]
            if prior < 0:
                continue
            scored.append((prior * info["size"] * info["arpu"], info["size"] * info["arpu"],
                           cell, target))
        # Positive-prior arms first by prior x value; with no informative prior (e.g. no
        # history table) the nearest upsell of the most valuable cells is still piloted.
        scored.sort(key=lambda x: (x[0] > 0, x[0], x[1]), reverse=True)
        return [(cell, target) for _, _, cell, target in scored]

    def run(self):
        first = {}
        for cell, target in self.candidates()[:V4_ROUND1_PILOTS]:
            if not self._can_pilot(ROUND1_N):
                break
            res = self.pilot(cell, target, ROUND1_N)
            if res is not None:
                first[(cell, target)] = res["observed_lift_ratio"]

        # Winner's-curse check: the top arms by observed ratio get a second look, then
        # the remaining re-check pilots go to the best pooled estimates that stay positive.
        top = sorted((arm for arm, ratio in first.items() if ratio > 0),
                     key=lambda arm: first[arm], reverse=True)[:V4_RECHECK_ARMS]
        rechecks = 0
        for cell, target in top:
            if rechecks >= V4_RECHECK_PILOTS or not self._can_pilot(ROUND2_N):
                break
            if self.pilot(cell, target, ROUND2_N) is not None:
                rechecks += 1
        while rechecks < V4_RECHECK_PILOTS and self._can_pilot(ROUND2_N):
            alive = [(self.post.pilot_only(cell, target)[0], cell, target) for cell, target in top
                     if self.post.pilot_only(cell, target)[0] > 0]
            if not alive:
                break
            _, cell, target = max(alive)
            if self.pilot(cell, target, ROUND2_N) is None:
                break
            rechecks += 1
        return self.log


class PlannerV4(Planner):
    """Launch every arm with pooled pilot estimate > 0 and posterior mean > 0 (optionally
    only the `max_finals` best by expected total net)."""

    def __init__(self, env, cells, posterior, pilot_log, max_finals=None):
        super().__init__(env, cells, posterior, pilot_log)
        self.max_finals = max_finals

    def qualifying(self):
        best = {}
        for cell, target in sorted(self._tested()):
            mean, _ = self.post.get(cell, target)
            pilot = self.post.pilot_only(cell, target)
            if mean <= 0 or pilot is None or pilot[0] <= 0:
                continue
            if cell not in best or mean > best[cell][1]:
                best[cell] = (target, mean)
        if self.max_finals is not None and len(best) > self.max_finals:
            ranked = sorted(best.items(), key=lambda kv: self._rank_value(kv[0], kv[1][1], 0.0),
                            reverse=True)
            best = dict(ranked[:self.max_finals])
        return best

    def _rank_value(self, cell, mean, _best_pc):
        """Expected total net of the whole cell alone, under the full post-pilot budget."""
        reach, money = self.env.remaining_contacts, self.env.remaining_budget
        return _best_assignment(self._parts(cell, None), mean, self.env.channels, reach, money)[0]
