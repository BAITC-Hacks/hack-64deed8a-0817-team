"""Beeline campaign agent: explore with single-cell pilots, exploit confident cells."""

from agent_core import priors_history
from agent_core.bayes import Posterior
from agent_core.cells import build_cells
from agent_core.explorer import Explorer
from agent_core.planner import Planner
from agent_core.priors import set_prior_source


class Agent:
    def act(self, env):
        set_prior_source(priors_history.get_prior)
        cells = build_cells(env.customer_profile)
        post = Posterior()
        explorer = Explorer(env, cells, post)
        pilot_log = explorer.run()
        self.pilot_log = pilot_log
        return Planner(env, cells, post, pilot_log).plan()
