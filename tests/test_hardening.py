"""Edge guards: empty audience, all-negative fallback contacts nobody, LLM gating/deadline."""

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import agent_core.llm_advisor as llm_advisor
from agent import Agent
from agent_core.bayes import Posterior
from agent_core.cells import build_cells
from agent_core.llm_advisor import LLMAdvisor
from agent_core.planner import Planner
from agent_core.priors import set_prior_source, weak_prior
from agent_core.v4 import PlannerV4
from environment import make_environment
from mock_environment import CHANNELS, MAX_TOTAL_CONTACTS, TOTAL_BUDGET, _mock_fallback, _mock_impact_model
from scoring_core import apply_filters, sanitize_campaigns

PROFILE = pd.read_csv(REPO_ROOT / "customer_profile.csv")
TARIFFS = pd.read_csv(REPO_ROOT / "data" / "dict_tariff.csv")
MODEL = _mock_impact_model(pd.read_csv(REPO_ROOT / "data" / "change_tariff.csv"))


def mock_env(profile, seed=1):
    return make_environment(customer_profile=profile, impact_model=MODEL, dict_tariff=TARIFFS,
                            channels=CHANNELS, total_budget=TOTAL_BUDGET,
                            max_total_contacts=MAX_TOTAL_CONTACTS,
                            fallback_predict=_mock_fallback, seed=seed)


def test_empty_audience_never_crashes():
    env, _ = mock_env(PROFILE.iloc[:0])
    campaigns = Agent().act(env)
    assert len(sanitize_campaigns(campaigns, env.tariffs)) == 1


@pytest.mark.parametrize("planner_cls", [Planner, PlannerV4])
def test_all_negative_fallback_contacts_nobody(planner_cls):
    env, _ = mock_env(PROFILE)
    set_prior_source(weak_prior)
    cells = build_cells(env.customer_profile)
    post = Posterior()
    log = []
    for cell, target in [(("tariff_8", "HIGH"), "tariff_10"), (("tariff_8", "MID"), "tariff_10")]:
        for _ in range(2):
            post.update(cell, target, -0.3, 200, CHANNELS["sms"]["conversion_multiplier"])
            log.append({"current_tariff": cell[0], "arpu_segment": cell[1], "target_tariff": target,
                        "n": 200, "cost": 800})
    campaigns = planner_cls(env, cells, post, log).plan()
    assert len(sanitize_campaigns(campaigns, env.tariffs)) == 1
    segment = apply_filters(env.customer_profile, pd.Series(campaigns[0]))
    assert len(segment) == 0


def test_llm_requires_opt_in_even_with_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("AGENT_USE_LLM", raising=False)
    assert not LLMAdvisor().enabled
    monkeypatch.setenv("AGENT_USE_LLM", "1")
    assert LLMAdvisor().enabled


def test_llm_hard_deadline_falls_back(monkeypatch):
    import time
    monkeypatch.setattr(llm_advisor, "TIMEOUT_S", 0.2)

    def hanging(messages, schema_name, schema):
        time.sleep(2)
        return {"remove": ["a"], "reason": "late"}

    adv = LLMAdvisor(transport=hanging)
    campaigns = [{"campaign_name": "a"}]
    started = time.monotonic()
    assert adv.review_finals(campaigns, []) == campaigns
    assert time.monotonic() - started < 1.5
    assert adv.log[-1]["status"] == "failed" and "TimeoutError" in adv.log[-1]["error"]
