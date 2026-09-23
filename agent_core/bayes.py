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
        return new_mean, math.sqrt(new_var)

    def lcb(self, cell, target, k=1.0):
        mean, sd = self.get(cell, target)
        return mean - k * sd

    def ucb(self, cell, target, k=1.0):
        mean, sd = self.get(cell, target)
        return mean + k * sd
