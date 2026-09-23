# Beeline case — mechanics (read from source, 2026-09-23)

Pack: `~/hackathon-prep/pack/` (read-only copy of `~/Downloads/beeline_case_participants.zip`).
Files: `environment.py` (the env, **same class used by the judges**), `scoring_core.py` (**same scoring
used by the judges**), `mock_environment.py` (mock effects + fallback, local only), `local_eval.py`,
`make_submission.py`, `agent_template.py`, `customer_profile.csv`, `data/*.csv`, dictionaries, guide.

---

## 1. The effect model (what everything is built on)

Per customer, the true relative effect depends **only** on `(current_tariff, arpu_segment, target_tariff, channel)`:

```
ratio  = arpu_change_pct[cur, seg, target] * min(conversion_rate[cur, seg, target] * channel_mult, 1.0)
lift_i = ratio * predicted_arpu_i
```

- `data_segment` / `call_segment` do **not** change the ratio. They only change *who* is in the
  segment (size, predicted_arpu mix). Same for judging: `_true_lift_ratio` and `score_campaign` merge
  on `current_tariff, arpu_segment` only — that is structural code, not mock.
- If `(cur, seg, target)` is missing from the impact model → `fallback_predict(...)` is used
  (mock: `0.4 * (price_target - price_cur) / median_price`, conversion = median conversion ≈ 0.092).
  In the mock, **66% of cell×target combos go through the fallback** (history only has 9 target tariffs).
- Channel multiplier is linear on conversion (clip at 1.0 almost never binds: conversion is a share
  of transitions, median 0.09). ⇒ a pilot on one channel tells you the ratio on every other channel:
  `ratio_ch2 ≈ ratio_ch1 * mult_ch2 / mult_ch1`.
- Audience: 23,441 customers, **63 (tariff × arpu_segment) cells**, only 21 cells with ≥200 people,
  7 with ≥1000. Biggest: tariff_8/HIGH 4726, tariff_10/HIGH 2950, tariff_4/HIGH 2108, tariff_8/MID 1720.
  HIGH segment = 13,918 people, mean predicted_arpu ≈ 7,970 (MID ≈ 4,690, LOW ≈ 2,860).
- History (`data/change_tariff.csv`, 14,823 rows) has **zero ID overlap** with the audience — it is a prior only.

## 2. `run_pilot` — sampling, noise, return value

```python
env.run_pilot(target_tariff, channel, n_customers=100,
              filter_arpu_segment=None, filter_data_segment=None,
              filter_call_segment=None, filter_current_tariff=None)   # "t1;t2" allowed
```

- Validates channel / tariff (ValueError), `pilots_left > 0` (RuntimeError).
- `n` is clipped to **[10, 200]**, then to `min(n, len(segment), affordable)` where
  `affordable = remaining_contacts` (and `remaining_budget // cost` for paid channels).
  n_actual = 0 → RuntimeError (empty segment or no money/contacts).
- Sample: **uniform random** subsample of the filtered segment (seeded from env rng — agent cannot
  reproduce which IDs were picked).
- Observation: `observed_lift_ratio = mean(true ratio over picked) + N(0, 0.804 / sqrt(n_actual))`.
  - **One scalar noise draw for the whole pilot**, not per customer. Only the aggregate is returned.
  - Noise std is in *ratio* units and **does not depend on channel**. Signal does (× channel mult).
    So SNR ∝ multiplier: push pilot measures the base effect with 1/0.5 = 2× amplified noise,
    call pilot with 1/1.2. std: n=30 → 0.147, n=100 → 0.080, n=150 → 0.066, n=200 → 0.057.
  - Unweighted mean over customers (not ARPU-weighted). Single-cell pilot ⇒ ratio of that cell + noise.
    Multi-cell pilot ⇒ mixture proportional to cell sizes — hard to decompose.
- Returns dict: `pilot, target_tariff, channel, n_customers, cost, observed_lift_ratio,
  observed_lift_total (= ratio × sum predicted_arpu of picked), remaining_budget, remaining_contacts`.
  **Filters are NOT in the result or in `env.pilot_history`** → the agent must record its own filters.
- Side effects: `remaining_budget -= n*cost`, `remaining_contacts -= n`, `pilots_left -= 1`,
  picked IDs are stored (organizer side) as an `explicit_ids` campaign that gets scored.

Mock scale check: with push, median true ratio of history-backed combos is 0.004 (IQR −0.009…0.03,
max 0.34) vs pilot std 0.057 at n=200 → in the mock most single pilots are basically noise.
The guide's “30 customers misreads a moderately profitable segment ~1 in 4” matches ratio ≈ 0.1
(Φ(−0.1/0.147) ≈ 0.25; at n=200 Φ(−1.76) ≈ 0.04) — the judge effects may be larger than the mock.

## 3. Net result (`scoring_core.score_campaigns`)

Campaign list scored = **pilots first (explicit_ids), then final campaigns in returned order**.
For each campaign, in order:

1. segment = filters applied (pilots: exactly their picked IDs), **sorted by ID_NUMBER**;
2. truncate to **5,000** (the *lowest IDs*, not best customers) — silently, extra doesn't count;
3. truncate to remaining reach (15,000 total incl. pilots);
4. paid channel: truncate to `remaining_money // cost` (100,000 total incl. pilots). Push is not
   money-limited;
5. cost = contacts × channel cost; lift per customer = ratio × predicted_arpu.

Then **dedup**: for every unique customer take `max` lift across all campaigns (pilots included).
`net = sum(best lift per unique customer) − total cost of ALL contacts (duplicates pay again)`.

Consequences:
- Negative lift is counted (no floor at 0) if no other campaign gives that customer something better.
- A negative pilot customer can be “repaired” by a later final campaign that covers them with a
  positive effect (max wins) — but you pay the contact again.
- Duplicating a campaign / overlapping segments = pure cost, no extra lift.
- Order matters: an early big campaign can eat the reach/money of later ones; truncation never raises.
  The env's `remaining_budget/contacts` is **not** decremented by finals — the agent must do its own
  accounting (reach left = 15,000 − pilot contacts; money left = 100,000 − pilot cost).
- Invalid tariff/channel in a final → that campaign dropped with “Кампания … отброшена”
  (fails must-have #2). Unknown filter values → empty segment (no crash) in local_eval,
  but `validate_strategy` would raise on the CSV path. Max 10 finals (`[:10]`).

## 4. Pilot charging — is push free?

Money: yes, push costs 0 and is not limited by the money budget (pilot or final).
But it is **not free**:
- consumes 1 of 20 pilots and up to 200 of the 15,000 contacts;
- the pilot customers are really treated and scored at their **true** effect: a push pilot on a bad
  cell realizes that loss (e.g. ratio −0.05 on 200 HIGH customers ≈ −80k, worth 500 calls);
- lowest SNR of all channels (mult 0.5) — an n=200 push pilot is as noisy (in base-effect terms) as
  an n≈35 call pilot.
Paid pilot prices at n=200: sms 800, digital_ads 4,400, call 32,000 (a third of the budget).

Budget reality: calls cap at 625 contacts total, digital at ~4,500, sms at 25,000 (> reach cap).
Reach (15,000) and pilots (20) are the real binding constraints for push/sms; money binds for call/ads.
Oracle on mock (ignores caps) says `call` is the per-customer winner in the best cells
(ratio × ARPU ≈ 0.3 × 4,700 ≈ 1,400 ≫ 160), so a mixed plan — push/sms on large positive cells,
call/ads on a small high-value slice — is the shape to aim for. Sum of all positive best-per-cell
oracle nets on mock ≈ 8.9M (ignores caps; upper bound only).

## 5. Structural vs mock (what changes at judging)

Structural (same code at judging): `environment.py` (pilot sampling, noise 0.804/√n, clip 10–200,
20 pilots, filters), `scoring_core.py` (order, 5,000 cap by ID, 15,000 reach, 100k budget, dedup max,
cost formula), channel costs & multipliers, the `ratio = pct × min(conv × mult, 1)` form,
`(tariff, arpu_segment)` granularity, customer_profile (same audience file), baseline 150,641,084.

Mock only (different at judging): the impact table (`arpu_change_pct`, `conversion_rate` per
from/to/segment — mock = simple averages of history; judges' = “real behaviour of the target
audience, noticeably different from history”), the fallback rule for missing combos, noise seed.
Do not tune to mock numbers; tune the exploration/decision logic.

## 6. What the agent can access at runtime

- `env.customer_profile` (DataFrame copy), `env.tariffs` (dict_tariff copy), `env.channels`
  (costs & multipliers — read from here, don't hardcode), `env.total_budget`, `env.max_total_contacts`,
  `env.remaining_budget`, `env.remaining_contacts`, `env.pilots_left`, `env.pilot_history`, `env.run_pilot`.
- `data/`: local_eval / make_submission run with cwd = pack dir and themselves read `data/…` and
  `customer_profile.csv` by relative path. The template does **not** read data/ (only env.customer_profile)
  but its comments recommend `data/change_tariff.csv` for priors. Judges re-run make_submission on the
  mock, so data/ will exist there; for the hidden env it's not stated → load via path relative to
  `__file__`, wrap in try/except, degrade to profile+tariff-price priors if missing.
- Not provided: an automatic checker script. Don't import `mock_environment` / `scoring_core` /
  `environment` internals in the agent (`_mock_impact_model` = reading the mock answer).

## 7. Forbidden patterns / rules (from guide + env docstring; checker itself not in pack)

Annulment: accessing env internals bypassing pilots — explicitly `__closure__`, `gc`, “reading
organizer files and similar”. Assume a grep for: `__closure__`, `cell_contents`, `gc.`, `inspect`,
`__globals__`, `__code__`, `sys._getframe`, `ctypes`, `_Internals`/`internals`, `executed_pilot_campaigns`,
`_rng`, `_model`, imports of `mock_environment`/`environment`/`scoring_core`.
Also: no hardcoded secrets — LLM key only from `os.environ["OPENAI_API_KEY"]`; must use pilots
(`Пилотов проведено > 0`) and base decisions on them; 1–10 valid campaigns; within limits;
`submission.csv` must be reproducible from `make_submission.py` with SUBMISSION_SEED=42 (seed any RNG;
LLM output must not break reproducibility — temperature 0 + deterministic fallback, or LLM advisory only).
Runtime: guide says ≤10 min incl. LLM calls; template docstring says ≤5 min and “no internet” —
**target <5 min and work fully without the LLM**.

## 8. Baseline (agent_template.py as agent.py, run in scratch copy, Python 3.12, pandas 3.0.2)

`python3 local_eval.py` (seed 42): **net −1,035,279** (−0.687%), gross −1,012,999, cost 22,280,
6 pilots (sms, n=150), 2 finals, 5,570 contacts, risk 66% negative. One final
(`tariff_10/HIGH → tariff_8`, chosen off a lucky noisy pilot) alone lost −1,007,245 — winner's curse.

`python3 local_eval.py --runs 10`: median **−357,948**, min −1,019,431, max −76,493, **0/10 positive**.
Runtime ≈ 1 s per run.

## 9. Top-5 design implications

1. **Think in cells, not segments.** Unit of decision = (current_tariff, arpu_segment) × target.
   Pilot one cell at a time (filter_current_tariff + filter_arpu_segment) so the observation is
   clean; data/call filters are only for sizing/splitting. Only ~20 cells are big enough to matter.
2. **Bayesian shrinkage + downside guard.** Prior from history (change_tariff → pct, conversion
   per cell/target, with wide variance since judge effects differ), posterior with noise
   0.804/√n / channel_mult. Launch a final only if a lower bound (e.g. mean − 1σ) of
   ratio×ARPU×n − cost is > 0. This alone kills the template's −1M winner's-curse failure.
3. **Explore cheaply, extrapolate across channels.** Ratio scales linearly with channel mult, so
   pilot with sms (cheap, 1.3× push SNR) or push (free money, but real loss on bad cells & noisy),
   spend n=150–200 on the few high-prior cells, adaptive: re-pilot only close-call leaders.
   Never pilot with call (32k per 200).
4. **Allocate as a knapsack under both caps.** 15,000 reach (minus pilots), 100k money (minus pilots),
   5,000/campaign (lowest-ID truncation — split big cells via data_segment), 10 campaigns, dedup max.
   Push/sms to wide positive cells; spend the money on call/ads only for the highest ratio×ARPU cells.
   Do own accounting, order finals by value, no overlapping segments, include pilot cells in finals
   when positive (their IDs get re-counted, only paid again).
5. **Robust & reproducible by construction.** Read costs/multipliers from env.channels, seed
   everything, LLM optional/advisory with try/except + deterministic fallback, <5 min, no imports of
   organizer modules, data/ loaded relative to __file__ with fallback. If nothing is confidently
   positive → return 1 minimal safe campaign rather than gamble (sign stability over --runs 10).
