"""Evaluate Agent against perturbed mock effects, separate from agent runtime.

Run from any directory: ``python tools/stress_eval.py``. Seeds 0..9 are used
for both pilot noise and the stochastic effect-table variants.
"""

from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import Agent
from environment import make_environment
from mock_environment import (
    CHANNELS,
    MAX_TOTAL_CONTACTS,
    TOTAL_BUDGET,
    _mock_fallback,
    _mock_impact_model,
)
from scoring_core import MAX_CAMPAIGNS, sanitize_campaigns, score_campaigns


VARIANTS = (
    "baseline",
    "arpu_x0.5",
    "arpu_x1.5",
    "row_random_0.5_to_1.5",
    "flip_20pct_positive",
    "conversion_x0.5",
)
FILTER_COLUMNS = (
    "filter_arpu_segment",
    "filter_data_segment",
    "filter_call_segment",
    "filter_current_tariff",
    "explicit_ids",
)


def perturb_effects(base: pd.DataFrame, variant: str, seed: int) -> pd.DataFrame:
    """Return an independent impact table for one variant and seed."""
    effects = base.copy(deep=True)
    rng = np.random.default_rng(seed)
    if variant == "baseline":
        pass
    elif variant == "arpu_x0.5":
        effects["arpu_change_pct"] *= 0.5
    elif variant == "arpu_x1.5":
        effects["arpu_change_pct"] *= 1.5
    elif variant == "row_random_0.5_to_1.5":
        effects["arpu_change_pct"] *= rng.uniform(0.5, 1.5, len(effects))
    elif variant == "flip_20pct_positive":
        positive = np.flatnonzero(effects["arpu_change_pct"].to_numpy() > 0)
        selected = rng.choice(positive, size=round(0.2 * len(positive)), replace=False)
        effects.iloc[selected, effects.columns.get_loc("arpu_change_pct")] *= -1
    elif variant == "conversion_x0.5":
        effects["conversion_rate"] *= 0.5
    else:
        raise ValueError(f"Unknown variant: {variant}")
    return effects


def evaluate(seed: int, effects: pd.DataFrame, profile: pd.DataFrame,
             tariffs: pd.DataFrame) -> float:
    env, internals = make_environment(
        customer_profile=profile,
        impact_model=effects,
        dict_tariff=tariffs,
        channels=CHANNELS,
        total_budget=TOTAL_BUDGET,
        max_total_contacts=MAX_TOTAL_CONTACTS,
        fallback_predict=_mock_fallback,
        seed=seed,
    )
    campaigns = sanitize_campaigns(Agent().act(env), env.tariffs)[:MAX_CAMPAIGNS]
    pilots = internals.executed_pilot_campaigns()
    if not pilots or not campaigns:
        raise RuntimeError(f"seed {seed}: agent needs pilots and final campaigns")

    strategy = pd.DataFrame(pilots + campaigns)
    for column in FILTER_COLUMNS:
        if column not in strategy:
            strategy[column] = None
    result = score_campaigns(
        strategy, env.customer_profile, effects, env.tariffs,
        env.customer_profile["predicted_arpu"].sum(), _mock_fallback,
        team_id="stress_eval",
    )
    return float(result["net_arpu_gain"])


def main() -> None:
    history = pd.read_csv(ROOT / "data" / "change_tariff.csv")
    profile = pd.read_csv(ROOT / "customer_profile.csv")
    tariffs = pd.read_csv(ROOT / "data" / "dict_tariff.csv")
    base = _mock_impact_model(history)

    print("| Variant | Median net ARPU | Minimum net ARPU | Positive seeds |")
    print("| --- | ---: | ---: | ---: |")
    for variant in VARIANTS:
        results = []
        for seed in range(10):
            effects = perturb_effects(base, variant, seed)
            results.append(evaluate(seed, effects, profile, tariffs))
        print(f"| {variant} | {np.median(results):,.0f} | {min(results):,.0f} | "
              f"{sum(value > 0 for value in results)}/10 |", flush=True)


if __name__ == "__main__":
    main()
