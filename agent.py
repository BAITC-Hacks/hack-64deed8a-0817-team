"""Beeline campaign agent: explore with single-cell pilots, exploit confident cells."""

from agent_core import priors_history
from agent_core.bayes import Posterior
from agent_core.cells import build_cells
from agent_core.explorer import Explorer
from agent_core.llm_advisor import LLMAdvisor
from agent_core.planner import Planner
from agent_core.priors import set_prior_source


class Agent:
    def act(self, env):
        set_prior_source(priors_history.get_prior)
        cells = build_cells(env.customer_profile)
        post = Posterior()
        self.advisor = LLMAdvisor()  # inactive without OPENAI_API_KEY
        explorer = Explorer(env, cells, post, advisor=self.advisor)
        pilot_log = explorer.run()
        self.pilot_log = pilot_log
        campaigns = Planner(env, cells, post, pilot_log).plan()
        if self.advisor.enabled:
            campaigns = self.advisor.review_finals(campaigns, explorer.posterior_table())
        return campaigns
