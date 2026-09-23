# Effect-table stress evaluation

Run `.venv/bin/python tools/stress_eval.py` from the repository root (or invoke
the script by absolute path). The harness runs `Agent` on seeds 0–9 for each
variant. The same perturbed effect table is passed to the pilot environment and
the final scorer. The agent receives only the normal environment interface.
Results below use `main` at `98c0980`, including the v2 confirmation gate and
history priors from `aca319c`.

| Variant | Median net ARPU | Minimum net ARPU | Positive seeds |
| --- | ---: | ---: | ---: |
| Baseline (unperturbed mock) | 574,550 | 59,765 | 10/10 |
| `arpu_change_pct` ×0.5 | 119,374 | -487,099 | 6/10 |
| `arpu_change_pct` ×1.5 | 950,418 | 403,936 | 10/10 |
| Each table row's `arpu_change_pct` ×U(0.5, 1.5) | 582,382 | 121,551 | 10/10 |
| Flip the sign of 20% of positive table rows | 464,672 | -403,127 | 7/10 |
| `conversion_rate` ×0.5 | 45,723 | -270,647 | 7/10 |

Figures are net ARPU gain after communication cost, rounded to the nearest
whole unit. Positive means strictly greater than zero. Baseline uses the
unmodified mock impact table. Random row factors and
sign flips are regenerated deterministically for each seed. The fixed-scale
variants use the same effect table for all ten seeds; pilot sampling and noise
still vary by seed.

These changes apply to rows of the mock impact table. The existing fallback
formula for missing tariff combinations is unchanged; its conversion input is
the median of the perturbed table, so the conversion variant also halves that
input. This probes sensitivity to mock effects, not performance on the hidden
judge effects.
