# Effect-table stress evaluation

Run `.venv/bin/python tools/stress_eval.py` from the repository root (or invoke
the script by absolute path). The harness runs `Agent` on seeds 0–9 for each
variant. The same perturbed effect table is passed to the pilot environment and
the final scorer. The agent receives only the normal environment interface.

| Variant | Median net ARPU | Minimum net ARPU | Positive seeds |
| --- | ---: | ---: | ---: |
| `arpu_change_pct` ×0.5 | -105,535 | -387,814 | 0/10 |
| `arpu_change_pct` ×1.5 | -87,844 | -357,352 | 3/10 |
| Each table row's `arpu_change_pct` ×U(0.5, 1.5) | -106,838 | -367,332 | 2/10 |
| Flip the sign of 20% of positive table rows | -109,239 | -366,886 | 2/10 |
| `conversion_rate` ×0.5 | -99,381 | -377,893 | 0/10 |

Figures are net ARPU gain after communication cost, rounded to the nearest
whole unit. Positive means strictly greater than zero. Random row factors and
sign flips are regenerated deterministically for each seed. The fixed-scale
variants use the same effect table for all ten seeds; pilot sampling and noise
still vary by seed.

These changes apply to rows of the mock impact table. The existing fallback
formula for missing tariff combinations is unchanged; its conversion input is
the median of the perturbed table, so the conversion variant also halves that
input. This probes sensitivity to mock effects, not performance on the hidden
judge effects.
