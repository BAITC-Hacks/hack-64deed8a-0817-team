# Policy benchmark on mock effect variants

Run `.venv/bin/python tools/benchmark.py` from any directory. Results below
were measured with the frozen agent code from `f11ae2d` (2026-09-23), seeds 0–9, with the LLM
advisor disabled. Each policy receives the same variant and seed; its pilot
sampling and noise still depend on the policy's own pilot sequence. Effects
are changed only inside the harness, using the variants from
`tools/stress_eval.py`. The same effect table drives pilots and final scoring.
Net ARPU includes pilot and final contact costs; positive means strictly > 0.

| Variant | Policy | Median net | Worst net | Positive seeds | Ours / oracle |
| --- | --- | ---: | ---: | ---: | ---: |
| Baseline | Template | -357,948 | -1,019,431 | 0/10 | — |
| Baseline | Naive | 1,121,837 | 1,102,900 | 10/10 | — |
| Baseline | Ours | 3,541,278 | 1,759,226 | 10/10 | 71.0% |
| Baseline | V4 | 3,541,278 | 1,759,226 | 10/10 | — |
| Baseline | V4 top 1 | 1,588,624 | 938,188 | 10/10 | — |
| Baseline | V4 top 3 | 2,771,421 | 1,456,872 | 10/10 | — |
| Baseline | Oracle plan | 4,990,964 | 4,988,160 | 10/10 | — |
| `arpu_change_pct` ×0.5 | Template | -449,758 | -604,048 | 0/10 | — |
| `arpu_change_pct` ×0.5 | Naive | 607,519 | 548,807 | 10/10 | — |
| `arpu_change_pct` ×0.5 | Ours | 1,338,946 | 709,821 | 10/10 | 52.0% |
| `arpu_change_pct` ×0.5 | V4 | 1,338,946 | 709,821 | 10/10 | — |
| `arpu_change_pct` ×0.5 | V4 top 1 | 776,576 | 374,457 | 10/10 | — |
| `arpu_change_pct` ×0.5 | V4 top 3 | 1,130,976 | 570,124 | 10/10 | — |
| `arpu_change_pct` ×0.5 | Oracle plan | 2,576,336 | 2,574,935 | 10/10 | — |
| `arpu_change_pct` ×1.5 | Template | -349,439 | -1,495,388 | 0/10 | — |
| `arpu_change_pct` ×1.5 | Naive | 1,686,887 | 1,660,429 | 10/10 | — |
| `arpu_change_pct` ×1.5 | Ours | 5,396,619 | 4,935,557 | 10/10 | 71.9% |
| `arpu_change_pct` ×1.5 | V4 | 5,396,619 | 4,935,557 | 10/10 | — |
| `arpu_change_pct` ×1.5 | V4 top 1 | 2,598,322 | 2,165,155 | 10/10 | — |
| `arpu_change_pct` ×1.5 | V4 top 3 | 4,413,771 | 3,226,515 | 10/10 | — |
| `arpu_change_pct` ×1.5 | Oracle plan | 7,504,672 | 7,500,466 | 10/10 | — |
| Per-row ×U(0.5, 1.5) | Template | -346,007 | -1,203,938 | 0/10 | — |
| Per-row ×U(0.5, 1.5) | Naive | 1,133,782 | 1,035,651 | 10/10 | — |
| Per-row ×U(0.5, 1.5) | Ours | 3,654,359 | 2,803,758 | 10/10 | 72.4% |
| Per-row ×U(0.5, 1.5) | V4 | 3,654,359 | 2,803,758 | 10/10 | — |
| Per-row ×U(0.5, 1.5) | V4 top 1 | 1,839,506 | 1,364,945 | 10/10 | — |
| Per-row ×U(0.5, 1.5) | V4 top 3 | 3,043,220 | 2,463,502 | 10/10 | — |
| Per-row ×U(0.5, 1.5) | Oracle plan | 5,045,036 | 4,751,800 | 10/10 | — |
| Flip 20% of positive rows | Template | -357,948 | -1,019,431 | 0/10 | — |
| Flip 20% of positive rows | Naive | 790,376 | 344,375 | 10/10 | — |
| Flip 20% of positive rows | Ours | 2,488,809 | 604,754 | 10/10 | 57.4% |
| Flip 20% of positive rows | V4 | 2,488,809 | 604,754 | 10/10 | — |
| Flip 20% of positive rows | V4 top 1 | 1,352,353 | 490,378 | 10/10 | — |
| Flip 20% of positive rows | V4 top 3 | 2,244,459 | 743,695 | 10/10 | — |
| Flip 20% of positive rows | Oracle plan | 4,332,958 | 3,648,146 | 10/10 | — |
| `conversion_rate` ×0.5 | Template | -258,379 | -537,146 | 0/10 | — |
| `conversion_rate` ×0.5 | Naive | 607,519 | 548,807 | 10/10 | — |
| `conversion_rate` ×0.5 | Ours | 1,338,946 | 709,821 | 10/10 | 54.7% |
| `conversion_rate` ×0.5 | V4 | 1,338,946 | 709,821 | 10/10 | — |
| `conversion_rate` ×0.5 | V4 top 1 | 776,576 | 374,457 | 10/10 | — |
| `conversion_rate` ×0.5 | V4 top 3 | 1,130,976 | 570,124 | 10/10 | — |
| `conversion_rate` ×0.5 | Oracle plan | 2,445,666 | 2,444,264 | 10/10 | — |

The percent column is **our median net divided by the feasible oracle plan's
median net** for that variant. Values are rounded only for display.

## Policy definitions and limits

- **Template:** the unchanged `agent_template.py` agent, scored with its real
  pilot contacts and returned final campaigns.
- **Naive:** ranks one target per audience cell by the history prior times cell
  size and mean ARPU; pilots the top 10 arms once each (150 SMS contacts); then
  launches one SMS campaign on the arm with the highest observed pilot ratio if
  it is positive. There is no confirmation gate or posterior shrinkage.
- **Ours:** the unchanged `agent.py` using frozen v4 code from `f11ae2d`.
- **V4 / V4 top 1 / V4 top 3:** the same v4 policy explicitly selected with
  `Agent(policy="v4")`, with no final-campaign cap or with at most one or three
  finals. The default `Ours` and `V4` rows match, as expected.
- **Oracle plan:** sees the true variant effect table in the harness. It runs
  one 10-contact push pilot, chosen using true effects to satisfy the mandatory
  pilot rule. It then searches whole cells and their data/call slices for up to
  10 nonoverlapping final campaigns under the 15,000-contact, 100,000-money,
  and 5,000-per-campaign caps. The harness scores four greedy plan orderings
  with the official scorer and reports the best feasible result it finds.

The oracle plan is a **feasible perfect-information benchmark**, but the four
greedy searches do not certify the globally best feasible plan. To give a
mathematically valid upper bound, the harness also computes a relaxation:
each customer may receive their individually best positive net action, with
no reach, money, campaign-count, pilot, or segment-filter restrictions. Even a
plan with overlapping campaigns cannot exceed this bound, because duplicate
contacts add costs and the scorer counts only the largest lift per customer.

| Variant | Median certified upper bound | Ours / bound |
| --- | ---: | ---: |
| Baseline | 9,015,764 | 39.3% |
| `arpu_change_pct` ×0.5 | 4,269,339 | 31.4% |
| `arpu_change_pct` ×1.5 | 13,971,534 | 38.6% |
| Per-row ×U(0.5, 1.5) | 9,278,223 | 39.4% |
| Flip 20% of positive rows | 7,629,715 | 32.6% |
| `conversion_rate` ×0.5 | 3,999,579 | 33.5% |

Ours beats both naive and template in median net ARPU on every variant and is
positive in all 60 runs. The baseline median is 71.0% of the feasible oracle
plan's median. These numbers measure the local mock and its defined
perturbations, not hidden judge effects.
