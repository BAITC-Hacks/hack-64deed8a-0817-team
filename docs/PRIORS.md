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
In `agent.py`, set the source before the `Posterior` is created:

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

## Known interaction (not yet plugged in)

`python local_eval.py --runs 10` on the mock, from a scratch copy:

| prior | median | min | max | runs > 0 |
|---|---|---|---|---|
| `weak_prior` (current) | −75,435 | −362,354 | 67,988 | 3/10 |
| `priors_history.get_prior` | −111,320 | −382,465 | −32,648 | 0/10 |

Cause: `Explorer.candidates` ranks by UCB. Seen combos in big HIGH cells mostly
have mean ≤ 0 and sd = 0.05, so their UCB is below the unseen `(0, 0.1)`. Pilots
then go to targets that have no history. The prior itself is not wrong here. To
fix it, either rank candidates in `explorer.py` by something other than the raw
UCB, or lower `UNSEEN_SD` here. Tuning either one to the mock numbers is exactly
what MECHANICS.md warns against, so it needs a team decision.

## Tests

`python -m pytest tests/test_priors.py -v` (plain `unittest` also works).
