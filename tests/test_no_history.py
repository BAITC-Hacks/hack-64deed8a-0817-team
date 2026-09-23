"""C1: with no history table the agent must not pilot downgrades and must stay within limits."""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import agent_core.priors_history as priors_history
from agent import Agent
from environment import MAX_PILOTS
from mock_environment import make_mock_env, MAX_TOTAL_CONTACTS, TOTAL_BUDGET
from scoring_core import MAX_CAMPAIGNS, sanitize_campaigns


@pytest.fixture
def empty_history(monkeypatch):
    monkeypatch.setattr(priors_history, "load_table", lambda path=None: {})
    monkeypatch.setattr(priors_history, "_default", None)
    yield
    priors_history._default = None  # next caller reloads the real table


def test_load_table_warns_when_unreadable(caplog, tmp_path):
    with caplog.at_level("WARNING", logger="agent_core.priors_history"):
        assert priors_history.load_table(tmp_path / "missing.csv") == {}
    assert "history prior unavailable" in caplog.text


def test_load_table_reads_repo_data():
    assert len(priors_history.load_table()) > 0


@pytest.mark.parametrize("seed", [1, 2])
def test_no_history_pilots_only_upsell_and_respects_limits(empty_history, seed):
    env, internals = make_mock_env(seed=seed, data_dir=str(REPO_ROOT / "data"),
                                   profile_path=str(REPO_ROOT / "customer_profile.csv"))
    price = dict(zip(env.tariffs["tariff_plan_code"], env.tariffs["price_tariff"]))
    agent = Agent()
    campaigns = sanitize_campaigns(agent.act(env), env.tariffs)

    assert 1 <= len(campaigns) <= MAX_CAMPAIGNS
    assert 0 < len(internals.executed_pilot_campaigns()) <= MAX_PILOTS
    assert env.remaining_budget >= 0 and env.remaining_contacts >= 0
    assert env.remaining_contacts >= MAX_TOTAL_CONTACTS - 20 * 200
    assert env.remaining_budget <= TOTAL_BUDGET
    for p in agent.pilot_log:
        assert price[p["target_tariff"]] > price[p["current_tariff"]], p
