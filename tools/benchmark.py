"""Compare local campaign policies on mock effect variants (evaluation only).

Run from any directory with ``python tools/benchmark.py``. This module is never
imported by the submission agent. The oracle alone may read the true effects.
"""

import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import Agent as OurAgent
from agent_template import Agent as TemplateAgent
from agent_core.priors_history import get_prior
from environment import make_environment
from mock_environment import (
    CHANNELS, MAX_TOTAL_CONTACTS, TOTAL_BUDGET, _mock_fallback,
    _mock_impact_model,
)
from scoring_core import MAX_CAMPAIGNS, sanitize_campaigns, score_campaigns
from tools.stress_eval import VARIANTS, perturb_effects


FILTER_COLUMNS = (
    "filter_arpu_segment", "filter_data_segment", "filter_call_segment",
    "filter_current_tariff", "explicit_ids",
)
POLICIES = ("template", "naive", "ours", "v4", "v4_top1", "v4_top3", "oracle")
SEEDS = range(10)


class NaiveAgent:
    """Screen ten high-prior arms once, then launch the best observed arm."""

    def act(self, env):
        cells = (env.customer_profile
                 .groupby(["current_tariff", "arpu_segment"], observed=True)
                 .agg(size=("ID_NUMBER", "size"), arpu=("predicted_arpu", "mean"))
                 .reset_index())
        targets = list(env.tariffs["tariff_plan_code"])
        arms = []
        for row in cells.itertuples(index=False):
            if row.size < 150:
                continue
            cell = (row.current_tariff, row.arpu_segment)
            target = max((t for t in targets if t != cell[0]),
                         key=lambda t: get_prior(cell, t)[0])
            prior = get_prior(cell, target)[0]
            arms.append((prior * row.size * row.arpu, cell, target))
        arms.sort(key=lambda item: item[0], reverse=True)

        observed = []
        for _, cell, target in arms[:10]:
            result = env.run_pilot(
                target_tariff=target, channel="sms", n_customers=150,
                filter_current_tariff=cell[0], filter_arpu_segment=cell[1],
            )
            observed.append((result["observed_lift_ratio"], cell, target))
        if not observed:
            return []
        ratio, cell, target = max(observed, key=lambda item: item[0])
        if ratio <= 0:
            return []
        return [{
            "campaign_name": "naive_best_observed",
            "filter_current_tariff": cell[0],
            "filter_arpu_segment": cell[1],
            "target_tariff": target,
            "channel": "sms",
        }]


def score_plan(campaigns, pilots, effects, profile, tariffs, name):
    strategy = pd.DataFrame(pilots + campaigns)
    if strategy.empty:
        return 0.0
    for column in FILTER_COLUMNS:
        if column not in strategy:
            strategy[column] = None
    result = score_campaigns(
        strategy, profile, effects, tariffs, profile["predicted_arpu"].sum(),
        _mock_fallback, team_id=name,
    )
    return float(result["net_arpu_gain"])


def evaluate_agent(agent, seed, effects, profile, tariffs, name):
    env, internals = make_environment(
        customer_profile=profile, impact_model=effects, dict_tariff=tariffs,
        channels=CHANNELS, total_budget=TOTAL_BUDGET,
        max_total_contacts=MAX_TOTAL_CONTACTS, fallback_predict=_mock_fallback,
        seed=seed,
    )
    campaigns = sanitize_campaigns(agent.act(env), env.tariffs)[:MAX_CAMPAIGNS]
    return score_plan(campaigns, internals.executed_pilot_campaigns(), effects,
                      env.customer_profile, env.tariffs, name)


def oracle_options(effects, profile, tariffs):
    """True-effect options for nonoverlapping one-campaign-per-cell plans."""
    rows = {
        (r.tariff_plan_code_from, str(r.arpu_segment), r.tariff_plan_code_to):
        (float(r.arpu_change_pct), float(r.conversion_rate))
        for r in effects.itertuples(index=False)
    }
    fallback_conversion = float(effects["conversion_rate"].median())
    targets = list(tariffs["tariff_plan_code"])
    options = {}
    for cell, sub in profile.groupby(["current_tariff", "arpu_segment"], observed=True):
        sub = sub.sort_values("ID_NUMBER")
        slices = [({}, sub)]
        for column in ("data_segment", "call_segment"):
            slices.extend(({f"filter_{column}": value}, part)
                          for value, part in sub.groupby(column, observed=True))
        for (data, call), part in sub.groupby(["data_segment", "call_segment"], observed=True):
            slices.append(({"filter_data_segment": data,
                            "filter_call_segment": call}, part))

        cell_options = []
        for channel, config in CHANNELS.items():
            multiplier = config["conversion_multiplier"]
            best_ratio, best_target = float("-inf"), None
            for target in targets:
                if target == cell[0]:
                    continue
                pair = rows.get((cell[0], cell[1], target))
                if pair is None:
                    pair = _mock_fallback(cell[0], target, cell[1], tariffs,
                                          fallback_conversion)
                pct, conversion = pair
                ratio = pct * min(conversion * multiplier, 1.0)
                if ratio > best_ratio:
                    best_ratio, best_target = ratio, target
            if best_ratio <= 0:
                continue
            for filters, part in slices:
                arpu = part.sort_values("ID_NUMBER")["predicted_arpu"].to_numpy()
                arpu = arpu[:5000]
                if not len(arpu):
                    continue
                prefix = np.r_[0.0, np.cumsum(arpu)]
                cell_options.append((best_ratio, best_target, channel, filters,
                                     prefix, config["cost_per_contact"]))
        if cell_options:
            options[cell] = cell_options
    return options


def oracle_pilot(options, seed, effects, profile, tariffs):
    """One true-effect-selected pilot satisfies the mandatory pilot rule."""
    best = None
    for cell, cell_options in options.items():
        for ratio, target, channel, filters, prefix, _ in cell_options:
            if channel != "push" or filters or len(prefix) <= 10:
                continue
            # The pilot samples randomly; use cell mean ARPU to rank choices.
            estimate = ratio * prefix[-1] / (len(prefix) - 1)
            if best is None or estimate > best[0]:
                best = (estimate, cell, target)
    if best is None:
        raise RuntimeError("Oracle found no cell for a pilot")
    _, cell, target = best
    env, internals = make_environment(
        customer_profile=profile, impact_model=effects, dict_tariff=tariffs,
        channels=CHANNELS, total_budget=TOTAL_BUDGET,
        max_total_contacts=MAX_TOTAL_CONTACTS, fallback_predict=_mock_fallback,
        seed=seed,
    )
    env.run_pilot(target_tariff=target, channel="push", n_customers=10,
                  filter_current_tariff=cell[0], filter_arpu_segment=cell[1])
    return (internals.executed_pilot_campaigns(), env.remaining_contacts,
            env.remaining_budget)


def oracle_plan(options, pilots, reach_left, money_left, effects, profile, tariffs):
    """Best of several greedy searches; each returned plan is scorer-feasible."""
    winners = []
    for mode in ("gain", "reach", "budget", "balanced"):
        reach, money = reach_left, money_left
        remaining = set(options)
        campaigns = []
        while remaining and len(campaigns) < MAX_CAMPAIGNS and reach > 0:
            best = None
            for cell in sorted(remaining):
                for ratio, target, channel, filters, prefix, cost in options[cell]:
                    n = min(len(prefix) - 1, reach)
                    if cost:
                        n = min(n, int(money // cost))
                    if n <= 0:
                        continue
                    gain = ratio * prefix[n] - cost * n
                    if gain <= 0:
                        continue
                    if mode == "gain":
                        priority = gain
                    elif mode == "reach":
                        priority = gain / n
                    elif mode == "budget":
                        priority = gain / (1 + cost * n / TOTAL_BUDGET)
                    else:
                        priority = gain / (n / MAX_TOTAL_CONTACTS
                                           + cost * n / TOTAL_BUDGET)
                    candidate = (priority, gain, cell, target, channel, filters, n, cost)
                    if best is None or candidate[:2] > best[:2]:
                        best = candidate
            if best is None:
                break
            _, _, cell, target, channel, filters, n, cost = best
            campaigns.append({
                "campaign_name": f"oracle_{len(campaigns) + 1}",
                "filter_current_tariff": cell[0],
                "filter_arpu_segment": cell[1],
                "target_tariff": target,
                "channel": channel,
                **filters,
            })
            remaining.remove(cell)
            reach -= n
            money -= cost * n
        net = score_plan(campaigns, pilots, effects, profile, tariffs, "oracle")
        winners.append((net, campaigns))
    return max(winners, key=lambda item: item[0])


def relaxed_upper_bound(options, profile):
    """Certified upper bound: each customer gets their best net action for free.

    Drops reach, money, campaign-count and segment-filter restrictions. Any
    actual plan, including pilots and duplicates, can only do worse.
    """
    # Ratios/targets do not vary within a cell; slices only change eligibility.
    # The full-cell option is always present, so it covers every possible action.
    ceiling = 0.0
    for cell, sub in profile.groupby(["current_tariff", "arpu_segment"], observed=True):
        if cell not in options:
            continue
        arpu = sub["predicted_arpu"].to_numpy()
        best = np.zeros(len(arpu))
        for ratio, _, _, filters, _, cost in options[cell]:
            if filters:
                continue
            best = np.maximum(best, ratio * arpu - cost)
        ceiling += best.sum()
    return float(ceiling)


def summarize(values):
    values = np.asarray(values, dtype=float)
    return f"{np.median(values):,.0f}", f"{values.min():,.0f}", f"{np.count_nonzero(values > 0)}/10"


def main():
    # Keep policy comparisons deterministic and offline even on machines with a key.
    os.environ.pop("OPENAI_API_KEY", None)
    profile = pd.read_csv(ROOT / "customer_profile.csv")
    tariffs = pd.read_csv(ROOT / "data" / "dict_tariff.csv")
    history = pd.read_csv(ROOT / "data" / "change_tariff.csv")
    base = _mock_impact_model(history)

    print("| Variant | Policy | Median net | Worst net | Positive | Ours / oracle |", flush=True)
    print("| --- | --- | ---: | ---: | ---: | ---: |", flush=True)
    bounds_summary = []
    for variant in VARIANTS:
        runs = {policy: [] for policy in POLICIES}
        upper_bounds = []
        for seed in SEEDS:
            effects = perturb_effects(base, variant, seed)
            for name, agent_type in (("template", TemplateAgent),
                                     ("naive", NaiveAgent), ("ours", OurAgent),
                                     ("v4", lambda: OurAgent(policy="v4")),
                                     ("v4_top1", lambda: OurAgent(policy="v4", max_finals=1)),
                                     ("v4_top3", lambda: OurAgent(policy="v4", max_finals=3))):
                runs[name].append(evaluate_agent(agent_type(), seed, effects,
                                                 profile, tariffs, name))
            options = oracle_options(effects, profile, tariffs)
            pilots, reach_left, money_left = oracle_pilot(
                options, seed, effects, profile, tariffs)
            oracle_net, _ = oracle_plan(options, pilots, reach_left, money_left,
                                        effects, profile, tariffs)
            bound = relaxed_upper_bound(options, profile)
            if oracle_net > bound + 1e-5 or runs["ours"][-1] > bound + 1e-5:
                raise AssertionError("Relaxed upper bound was violated")
            runs["oracle"].append(oracle_net)
            upper_bounds.append(bound)
        for name in POLICIES:
            median, worst, positive = summarize(runs[name])
            pct = (f"{100 * np.median(runs['ours']) / np.median(runs['oracle']):.1f}%"
                   if name == "ours" else "—")
            print(f"| {variant} | {name} | {median} | {worst} | {positive} | {pct} |",
                  flush=True)
        bounds_summary.append((variant, np.median(upper_bounds),
                               np.median(runs["ours"])))

    print("\nCertified relaxed upper bound (no resource or segmentation limits):")
    print("| Variant | Median bound | Ours / bound |")
    print("| --- | ---: | ---: |")
    for variant, bound, ours in bounds_summary:
        print(f"| {variant} | {bound:,.0f} | {100 * ours / bound:.1f}% |")


if __name__ == "__main__":
    main()
