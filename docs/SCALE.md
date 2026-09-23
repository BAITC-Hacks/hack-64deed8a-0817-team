# Scale test

`python tools/scale_test.py` (harness only; the agent never imports it).

## Method

- `customer_profile.csv` is copied 1×, 10× and 100×. Copy `k` gets
  `ID_NUMBER + k × (max ID + 1)`, so all IDs are unique. Only the columns the
  agent reads are loaded: `ID_NUMBER`, `current_tariff`, `arpu_segment`,
  `data_segment`, `call_segment`, `predicted_arpu`.
- Timed: `build_cells(profile)` and `Planner(...).plan()`. No env and no pilots.
  The 10 largest cells, each moved to the most expensive other tariff, are
  passed through the real `Posterior` (2 pilots each), so they clear the
  planner gate. `plan()` does its full work every time: qualifying, per-cell
  filtering and sorting by ID, and channel assignment.
- Each value is the median of 5 repeats (1×, 10×) or 3 repeats (100×).

## Results

Measured 23.09.2026 on an Apple M4 with 16 GB RAM, macOS (Darwin arm64),
Python 3.13.9 and pandas 3.0.6.

| Scale | Rows | Cells | build_cells, ms | Planner.plan, ms | Campaigns |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1× | 23,441 | 63 | 2.8 | 7.2 | 5 |
| 10× | 234,410 | 63 | 17.8 | 37.5 | 3 |
| 100× | 2,344,100 | 63 | 169.8 | 381.3 | 3 |

The whole script (all three sizes, all repeats) takes 2.6 s. Peak memory
(RSS) is 470 MB.

## Reading

- Both steps grow about linearly with the number of rows: ×10 rows gives
  roughly ×5–10 time. The number of cells does not grow (63), because
  replication does not add new tariffs or segments.
- `plan()` scans the full profile once per qualifying cell (`_parts` filters
  and sorts by ID). Its cost is O(rows × qualifying cells), capped at 10
  campaigns. At 100× it is 0.4 s, far inside the 10-minute limit.
- Fewer campaigns at 10× and 100× is expected and not a slowdown. Each cell
  is larger than the 5,000-per-campaign cap, so three campaigns use up the
  15,000-contact reach.
- Not measured: pilots (`env.run_pilot` belongs to the organizers' env) and
  `Explorer._cheapest_slice`, which does one groupby per pilot on the cell's
  rows. It scales in the same linear way as `build_cells`.
