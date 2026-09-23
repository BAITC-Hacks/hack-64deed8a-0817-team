# Effect-table stress evaluation

Run `.venv/bin/python tools/stress_eval.py` from the repository root (or invoke
the script by absolute path). The harness runs `Agent` on seeds 0–9 for each
variant. The same perturbed effect table is passed to the pilot environment and
the final scorer. The agent receives only the normal environment interface.
Results below use the frozen agent code from `f11ae2d` (v4 wide screening).

| Variant | Median net ARPU | Minimum net ARPU | Positive seeds |
| --- | ---: | ---: | ---: |
| Baseline (unperturbed mock) | 3,541,278 | 1,759,226 | 10/10 |
| `arpu_change_pct` ×0.5 | 1,338,946 | 709,821 | 10/10 |
| `arpu_change_pct` ×1.5 | 5,396,619 | 4,935,557 | 10/10 |
| Each table row's `arpu_change_pct` ×U(0.5, 1.5) | 3,654,359 | 2,803,758 | 10/10 |
| Flip the sign of 20% of positive table rows | 2,488,809 | 604,754 | 10/10 |
| `conversion_rate` ×0.5 | 1,338,946 | 709,821 | 10/10 |

Figures are net ARPU gain after communication cost, rounded to the nearest
whole unit. Positive means strictly greater than zero. Baseline uses the
unmodified mock impact table. Random row factors and
sign flips are regenerated deterministically for each seed. All 60 runs were
positive in this local mock check. The fixed-scale
variants use the same effect table for all ten seeds; pilot sampling and noise
still vary by seed.

These changes apply to rows of the mock impact table. The existing fallback
formula for missing tariff combinations is unchanged; its conversion input is
the median of the perturbed table, so the conversion variant also halves that
input. This probes sensitivity to mock effects, not performance on the hidden
judge effects.
