"""Beeline campaign agent: explore with single-cell pilots, exploit confident cells."""

import logging

from agent_core import priors_history
from agent_core.bayes import Posterior
from agent_core.cells import build_cells
from agent_core.explorer import Explorer
from agent_core.llm_advisor import LLMAdvisor
from agent_core.planner import Planner, safety_campaign
from agent_core.priors import set_prior_source
from agent_core.v4 import ExplorerV4, PlannerV4

# "v3": confirmation gate (2 pilots, mean - 1.5 sd > 0). "v4": wide screening, re-check,
# launch every pilot-positive arm (agent_core/v4.py). Benchmarked in docs/BENCHMARK.md.
POLICY = "v4"

logger = logging.getLogger(__name__)


class Agent:
    def __init__(self, policy=None, max_finals=None):
        self.policy = policy or POLICY
        self.max_finals = max_finals  # v4 only: launch at most this many finals

    def act(self, env):
        """Never raises: any failure returns one valid, cost-free push campaign."""
        try:
            return self._act(env)
        except Exception:  # noqa: BLE001 - the judge run must always get campaigns
            logger.exception("agent failed; returning the safety campaign")
            try:
                return [safety_campaign(env)]
            except Exception:  # noqa: BLE001
                return [{"campaign_name": "safety_net", "channel": "push",
                         "target_tariff": env.tariffs["tariff_plan_code"].iloc[0]}]

    def _act(self, env):
        set_prior_source(priors_history.get_prior)
        cells = build_cells(env.customer_profile)
        post = Posterior()
        self.advisor = LLMAdvisor()  # inactive without OPENAI_API_KEY
        if self.policy == "v4":
            explorer = ExplorerV4(env, cells, post, advisor=self.advisor)
            pilot_log = explorer.run()
            planner = PlannerV4(env, cells, post, pilot_log, max_finals=self.max_finals)
        else:
            explorer = Explorer(env, cells, post, advisor=self.advisor)
            pilot_log = explorer.run()
            planner = Planner(env, cells, post, pilot_log)
        self.pilot_log = pilot_log
        campaigns = planner.plan()
        if self.advisor.enabled:
            campaigns = self.advisor.review_finals(campaigns, explorer.posterior_table())
        return campaigns
