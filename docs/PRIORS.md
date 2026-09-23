# History prior (`agent_core/priors_history.py`)

Prior on the **base effect** of moving a cell to a target tariff, built from
`data/change_tariff.csv`. Everything here is our own estimate from the history
file; nothing is taken from `mock_environment.py`.

## Definitions

| Term | Definition |
|---|---|
| cell | `(current_tariff, arpu_segment)` of the audience |
| base effect | lift ratio at channel multiplier 1.0 (`ratio = base × mult`, see `bayes.py`) |
| from / to | `tariff_plan_code_from` / `tariff_plan_code_to` of a history row |
| `arpu_segment` | from `AVG_ARPU_PREV_3M` with the guide's thresholds: `< 1000` LOW, `1000–5000` MID, `> 5000` HIGH |
| relative change `pct` | `(AVG_ARPU_NEXT_3M − AVG_ARPU_PREV_3M) / AVG_ARPU_PREV_3M`, clipped to `[−1, 5]` |
| rows used | `AVG_ARPU_PREV_3M ≥ 50` (≈1,900 rows below that have a near-zero denominator; p99 of raw `pct` is ~26) |

Per `(from, arpu_segment, to)`:

- `n` — number of history switches;
- `mean`, `std` — mean and sample std of `pct` (`std = 0` when `n = 1`);
- `conv` — conversion proxy: share of switchers from `(from, arpu_segment)` that went
  to `to`, Laplace-smoothed: `(n + 1) / (N_from_seg + T)`, `T` = number of distinct
  targets in history (9). History contains only people who did switch, so this is
  a relative preference between targets, not a true response rate.

## Prior (mean, sd)

```
raw  = conv × mean
mean = raw × n / (n + 30)                    # shrink toward 0; small n → near 0
se   = conv × std / sqrt(n)
sd   = max(0.05, sqrt(se² + raw²))           # wide: judge effects differ from history
```

`sd ≥ |raw|` on purpose: the judges' effects are "noticeably different from
history", so we let the true effect be anywhere from ~0 to ~2× the history value.

No history for `(cell, target)` (most combos: history has only 9 target
tariffs) → `(0.0, 0.1)`, the same as `priors.weak_prior`. A missing or unreadable
CSV gives an empty table, so every call falls back to `(0.0, 0.1)`.

On the real file: 453 rows, prior mean median 0.003 (range −0.09…0.81), sd median
0.05 (range 0.05…1.09). Large values are LOW-segment rows where small ARPU makes
`pct` large.

## Plugging it in

The interface is `priors.set_prior_source(fn)`, where `fn(cell, target) -> (mean, sd)`.
`agent.py` already sets this source before the `Posterior` is created:

```python
from agent_core import priors_history
from agent_core.priors import set_prior_source

class Agent:
    def act(self, env):
        set_prior_source(priors_history.get_prior)
        cells = build_cells(env.customer_profile)
        post = Posterior()
        ...
```

`get_prior` reads the CSV once, on first call (~0.1 s).

## Known interaction (plugged in — a caveat)

`agent.py` uses `set_prior_source(priors_history.get_prior)`: the history prior
is the current source; `weak_prior` below is only a reference for comparison.
The numbers below are the previously recorded `python local_eval.py --runs 10`
results on the mock, from a scratch copy with the earlier UCB-based candidate
ranking. They are not measurements of the current agent:

| prior | median | min | max | runs > 0 |
|---|---|---|---|---|
| `weak_prior` (reference only) | −75,435 | −362,354 | 67,988 | 3/10 |
| `priors_history.get_prior` (current source; historical results) | −111,320 | −382,465 | −32,648 | 0/10 |

Cause in that comparison: `Explorer.candidates` ranked by UCB. Seen combos in big HIGH cells mostly
have mean ≤ 0 and sd = 0.05, so their UCB is below the unseen `(0, 0.1)`. Pilots
then go to targets that have no history. The prior itself is not wrong here. To
fix it, either rank candidates in `explorer.py` by something other than the raw
UCB, or lower `UNSEEN_SD` here. Tuning either one to the mock numbers is exactly
what MECHANICS.md warns against, so it needs a team decision.

The current `Explorer.candidates` already ranks cells by `size × arpu` and
targets within each cell by prior mean, not UCB. The comparison above documents
the interaction with the earlier ranking; further tuning remains a team decision.

## Tests

`python -m pytest tests/test_priors.py -v` (plain `unittest` also works).
