"""Must-have checks from PARTICIPANT_GUIDE.md section 7, run the same way local_eval.py does.

For seeds 1..5 on the mock env: agent runs without crashing, returns 1-10 valid
campaigns, actually used pilots, and stayed within the budget/contacts/pilot
limits enforced by environment.py. Runtime per seed must stay under 5 minutes
(guide's judging time limit).
"""

import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from agent import Agent
from environment import MAX_PILOTS, MAX_PILOT_CUSTOMERS, MIN_PILOT_CUSTOMERS
from mock_environment import make_mock_env, MAX_TOTAL_CONTACTS, TOTAL_BUDGET
from scoring_core import MAX_CAMPAIGNS, sanitize_campaigns

SEEDS = [1, 2, 3, 4, 5]
MAX_RUNTIME_SECONDS = 5 * 60


@pytest.mark.parametrize("seed", SEEDS)
def test_agent_respects_limits(seed):
    env, internals = make_mock_env(
        seed=seed,
        data_dir=str(REPO_ROOT / "data"),
        profile_path=str(REPO_ROOT / "customer_profile.csv"),
    )

    start = time.perf_counter()
    campaigns = Agent().act(env)
    elapsed = time.perf_counter() - start

    assert elapsed < MAX_RUNTIME_SECONDS, (
        f"seed {seed}: act() took {elapsed:.1f}s, must stay under "
        f"{MAX_RUNTIME_SECONDS}s"
    )

    valid_campaigns = sanitize_campaigns(campaigns, env.tariffs)
    assert 1 <= len(valid_campaigns) <= MAX_CAMPAIGNS, (
        f"seed {seed}: {len(valid_campaigns)} valid campaigns, "
        f"must have between 1 and {MAX_CAMPAIGNS}"
    )

    pilots = internals.executed_pilot_campaigns()
    assert len(pilots) > 0, f"seed {seed}: agent ran no pilots"
    assert len(pilots) <= MAX_PILOTS, (
        f"seed {seed}: {len(pilots)} pilots, limit is {MAX_PILOTS}"
    )

    for p in env.pilot_history:
        assert MIN_PILOT_CUSTOMERS <= p["n_customers"] <= MAX_PILOT_CUSTOMERS, (
            f"seed {seed}: pilot {p['pilot']} used {p['n_customers']} customers, "
            f"must be within [{MIN_PILOT_CUSTOMERS}, {MAX_PILOT_CUSTOMERS}]"
        )

    assert env.remaining_budget >= 0, (
        f"seed {seed}: overspent budget, remaining {env.remaining_budget}"
    )
    assert env.remaining_budget <= TOTAL_BUDGET, (
        f"seed {seed}: remaining budget {env.remaining_budget} exceeds total {TOTAL_BUDGET}"
    )
    assert env.remaining_contacts >= 0, (
        f"seed {seed}: over-contacted, remaining {env.remaining_contacts}"
    )
    assert env.remaining_contacts <= MAX_TOTAL_CONTACTS, (
        f"seed {seed}: remaining contacts {env.remaining_contacts} exceeds total {MAX_TOTAL_CONTACTS}"
    )
    assert env.pilots_left >= 0, f"seed {seed}: pilots_left went negative"
