"""Normal-normal posterior on the base effect per (cell, target).

A pilot on channel ch observes ratio = base * mult_ch + N(0, 0.804 / sqrt(n)),
so in base-effect units: obs = ratio / mult, sd = 0.804 / (sqrt(n) * mult).
"""

import math

from .priors import get_prior

PILOT_NOISE = 0.804


class Posterior:
    def __init__(self):
        self._state = {}  # (cell, target) -> (mean, var)
        self.n_obs = {}   # (cell, target) -> pilots observed
        self.n_total = {} # (cell, target) -> customers observed over all pilots
        self._pilot = {}  # (cell, target) -> (sum obs * precision, sum precision), prior ignored

    def get(self, cell, target):
        key = (cell, target)
        if key not in self._state:
            mean, sd = get_prior(cell, target)
            self._state[key] = (mean, sd * sd)
        mean, var = self._state[key]
        return mean, math.sqrt(var)

    def update(self, cell, target, observed_ratio, n, mult):
        mean, sd = self.get(cell, target)
        obs = observed_ratio / mult
        obs_var = (PILOT_NOISE / (math.sqrt(n) * mult)) ** 2
        prec = 1.0 / (sd * sd) + 1.0 / obs_var
        new_var = 1.0 / prec
        new_mean = new_var * (mean / (sd * sd) + obs / obs_var)
        self._state[(cell, target)] = (new_mean, new_var)
        self.n_obs[(cell, target)] = self.n_obs.get((cell, target), 0) + 1
        self.n_total[(cell, target)] = self.n_total.get((cell, target), 0) + n
        wsum, psum = self._pilot.get((cell, target), (0.0, 0.0))
        self._pilot[(cell, target)] = (wsum + obs / obs_var, psum + 1.0 / obs_var)
        return new_mean, math.sqrt(new_var)

    def lcb(self, cell, target, k=1.0):
        mean, sd = self.get(cell, target)
        return mean - k * sd

    def ucb(self, cell, target, k=1.0):
        mean, sd = self.get(cell, target)
        return mean + k * sd

    def confirmed_enough(self, cell, target, min_pilots=2, min_n=300):
        key = (cell, target)
        return self.n_obs.get(key, 0) >= min_pilots or self.n_total.get(key, 0) >= min_n

    def pilot_only(self, cell, target):
        """Pooled pilot estimate of the base effect, prior ignored; None if never piloted."""
        wsum, psum = self._pilot.get((cell, target), (0.0, 0.0))
        if psum <= 0:
            return None
        return wsum / psum, math.sqrt(1.0 / psum)
