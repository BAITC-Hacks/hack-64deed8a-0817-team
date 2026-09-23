"""History prior on the base effect per (cell, target), from data/change_tariff.csv.

Base effect = relative ARPU change x conversion at channel multiplier 1.0.
History is only a hint (judge effects differ from it), so the mean is shrunk
toward 0 and the sd is kept wide. Definitions: docs/PRIORS.md.

Plug in:  set_prior_source(priors_history.get_prior)
"""

import math
from pathlib import Path

import pandas as pd

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "change_tariff.csv"

LOW_MAX = 1000.0      # arpu_segment thresholds from the case guide (ARPU_3m_avg)
MID_MAX = 5000.0
MIN_PREV_ARPU = 50.0  # below this the relative change is dominated by the tiny denominator
PCT_CAP = 5.0         # relative change clipped to [-1, PCT_CAP]; tail beyond ~p95 is noise
SHRINK_K = 30.0       # pseudo-count: mean is scaled by n / (n + SHRINK_K)
SD_FLOOR = 0.05
UNSEEN_SD = 0.1       # no history for (cell, target): same as priors.weak_prior


def arpu_segment(arpu):
    if arpu < LOW_MAX:
        return "LOW"
    if arpu <= MID_MAX:
        return "MID"
    return "HIGH"


def load_table(path=DATA_PATH):
    """{(from_tariff, arpu_segment, to_tariff): {n, mean, std, conv}}; {} if unreadable."""
    try:
        df = pd.read_csv(path, usecols=["AVG_ARPU_PREV_3M", "AVG_ARPU_NEXT_3M",
                                        "tariff_plan_code_from", "tariff_plan_code_to"])
    except (OSError, ValueError):
        return {}

    df = df[df["AVG_ARPU_PREV_3M"] >= MIN_PREV_ARPU].copy()
    if df.empty:
        return {}
    df["segment"] = df["AVG_ARPU_PREV_3M"].map(arpu_segment)
    df["pct"] = ((df["AVG_ARPU_NEXT_3M"] - df["AVG_ARPU_PREV_3M"])
                 / df["AVG_ARPU_PREV_3M"]).clip(-1.0, PCT_CAP)

    keys = ["tariff_plan_code_from", "segment", "tariff_plan_code_to"]
    g = df.groupby(keys).agg(n=("pct", "size"), mean=("pct", "mean"),
                             std=("pct", "std")).reset_index()
    # Conversion proxy: share of switchers from (from, segment) that went to this
    # target, Laplace-smoothed over all targets seen in history.
    n_targets = df["tariff_plan_code_to"].nunique()
    total = g.groupby(["tariff_plan_code_from", "segment"])["n"].transform("sum")
    g["conv"] = (g["n"] + 1) / (total + n_targets)

    return {
        (r.tariff_plan_code_from, r.segment, r.tariff_plan_code_to): {
            "n": int(r.n),
            "mean": float(r.mean),
            "std": 0.0 if pd.isna(r.std) else float(r.std),
            "conv": float(r.conv),
        }
        for r in g.itertuples(index=False)
    }


def prior_from_stats(stats):
    """(mean, sd) of the base effect for one history row of load_table()."""
    n, conv = stats["n"], stats["conv"]
    raw = conv * stats["mean"]
    mean = raw * n / (n + SHRINK_K)
    se = conv * stats["std"] / math.sqrt(n)
    # Judge effects differ from history: uncertainty at least the size of the effect itself.
    sd = max(SD_FLOOR, math.sqrt(se * se + raw * raw))
    return mean, sd


def make_prior_source(table):
    def source(cell, target):
        stats = table.get((cell[0], cell[1], target))
        if stats is None:
            return 0.0, UNSEEN_SD
        return prior_from_stats(stats)
    return source


_default = None


def get_prior(cell, target):
    global _default
    if _default is None:
        _default = make_prior_source(load_table())
    return _default(cell, target)
