"""Priors on the base effect (ratio at channel multiplier 1.0) per (cell, target).

cell = (current_tariff, arpu_segment). The source is pluggable: call
set_prior_source(fn) with fn(cell, target) -> (mean, sd) to replace the default.
"""

WEAK_MEAN = 0.0
WEAK_SD = 0.1


def weak_prior(cell, target):
    return WEAK_MEAN, WEAK_SD


_source = weak_prior


def set_prior_source(fn):
    global _source
    _source = fn if fn is not None else weak_prior


def get_prior(cell, target):
    return _source(cell, target)
