"""Time cell aggregation and the planner on a replicated audience (1x, 10x, 100x).

Harness only; the agent never imports it. Run from any directory:
``python tools/scale_test.py``. No env pilots are run: the same 10 arms are
marked as confirmed-positive through the real Posterior, so Planner.plan does its
full work (qualifying, per-cell sorting by ID, channel assignment) at every size.
"""

from pathlib import Path
import platform
import statistics
import sys
import time
from types import SimpleNamespace

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent_core import priors
from agent_core.bayes import Posterior
from agent_core.cells import build_cells
from agent_core.planner import Planner
from mock_environment import CHANNELS, MAX_TOTAL_CONTACTS, TOTAL_BUDGET

FACTORS = (1, 10, 100)
REPEATS = {1: 5, 10: 5, 100: 3}
N_ARMS = 10
ARM_MEAN = 0.05          # base effect of the synthetic confirmed arms
PILOT_N = 200
PILOT_CHANNEL = "sms"
# Only the columns the agent reads; keeps the 100x frame (~2.3M rows) small.
COLUMNS = ["ID_NUMBER", "current_tariff", "arpu_segment", "data_segment",
           "call_segment", "predicted_arpu"]


def replicate(profile, factor):
    """factor copies of the audience; copy k gets IDs shifted by k * (max ID + 1)."""
    step = int(profile["ID_NUMBER"].max()) + 1
    copies = []
    for k in range(factor):
        c = profile.copy()
        c["ID_NUMBER"] = c["ID_NUMBER"] + k * step
        copies.append(c)
    out = pd.concat(copies, ignore_index=True)
    assert out["ID_NUMBER"].is_unique
    return out


def pick_arms(cells, tariffs):
    """N_ARMS largest cells, each to the most expensive tariff other than its own."""
    by_price = tariffs.sort_values(["price_tariff", "tariff_plan_code"], ascending=False)
    arms = []
    for cell in sorted(cells, key=lambda c: (-cells[c]["size"], c))[:N_ARMS]:
        target = next(t for t in by_price["tariff_plan_code"] if t != cell[0])
        arms.append((cell, target))
    return arms


def confirmed_posterior(arms):
    """Real Posterior with every arm through the planner gate (2 pilots, LCB > 0)."""
    arm_set = set(arms)
    priors.set_prior_source(lambda cell, target: (ARM_MEAN, 0.01) if (cell, target) in arm_set
                            else (0.0, 0.1))
    post = Posterior()
    mult = CHANNELS[PILOT_CHANNEL]["conversion_multiplier"]
    cost = CHANNELS[PILOT_CHANNEL]["cost_per_contact"] * PILOT_N
    log = []
    for cell, target in arms:
        for _ in range(2):
            post.update(cell, target, ARM_MEAN * mult, PILOT_N, mult)
            log.append({"current_tariff": cell[0], "arpu_segment": cell[1],
                        "target_tariff": target, "n": PILOT_N, "cost": cost})
    return post, log


def timed(fn, repeats):
    times, result = [], None
    for _ in range(repeats):
        t0 = time.perf_counter()
        result = fn()
        times.append(time.perf_counter() - t0)
    return statistics.median(times), result


def main():
    base = pd.read_csv(ROOT / "customer_profile.csv", usecols=COLUMNS)
    tariffs = pd.read_csv(ROOT / "data" / "dict_tariff.csv")
    arms = pick_arms(build_cells(base), tariffs)

    rows = []
    try:
        for factor in FACTORS:
            profile = replicate(base, factor)
            env = SimpleNamespace(customer_profile=profile, channels=CHANNELS, tariffs=tariffs,
                                  max_total_contacts=MAX_TOTAL_CONTACTS, total_budget=TOTAL_BUDGET)
            repeats = REPEATS[factor]
            t_cells, cells = timed(lambda: build_cells(profile), repeats)
            post, log = confirmed_posterior(arms)
            t_plan, campaigns = timed(lambda: Planner(env, cells, post, log).plan(), repeats)
            rows.append((factor, len(profile), len(cells), repeats, t_cells, t_plan, len(campaigns)))
            print(f"{factor:>4}x: rows {len(profile):>10,}  build_cells {t_cells * 1000:9.1f} ms  "
                  f"plan {t_plan * 1000:9.1f} ms  campaigns {len(campaigns)}", flush=True)
    finally:
        priors.set_prior_source(None)

    print(f"\nPython {platform.python_version()}, pandas {pd.__version__}, "
          f"{platform.system()} {platform.machine()}; median of the repeats\n")
    print("| Scale | Rows | Cells | Repeats | build_cells, ms | Planner.plan, ms | Campaigns |")
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for factor, n, n_cells, repeats, t_cells, t_plan, n_camp in rows:
        print(f"| {factor}x | {n:,} | {n_cells} | {repeats} | {t_cells * 1000:,.1f} | "
              f"{t_plan * 1000:,.1f} | {n_camp} |")


if __name__ == "__main__":
    main()
