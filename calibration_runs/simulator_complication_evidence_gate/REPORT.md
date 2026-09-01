# Simulator Complication compliance calibration gate

Date: 2026-09-01
Simulator: `gpt-5.6-luna`
Judge: `gpt-5.5`
Configuration: defects off; the separation flag was enabled, but the then-current
name comparator incorrectly treated `gpt-5.6-luna` and `gpt-5.5` as different
families. Both are GPT-5-family models, so model-family separation was not achieved.

## Scope

The gate evaluated the approved complication-aware
`simulator_goal_persistence` wording and the new
`simulator_complication_evidence` criterion against the 13 committed curated
Scenarios at N=3. It also ran the admitted ordinal-1 synthesized cell at N=3
through all five production simulator-compliance criteria. No mock behavior,
curated Scenario, ordinary Judge criterion, or existing compliance criterion
was changed.

## Honest first-pass result

The fixed curated denominator was **32/39**.

- 35 Episodes completed. Of these, 32 passed the ordinary Agent verdict and
  the four curated simulator-compliance criteria.
- Four active identities were lost when one received
  `429 credit_balance_exhausted` and the fail-fast calibration process
  cancelled the other three without preserving per-task attribution. They
  remain failures in the fixed denominator and were not replaced.
- Three completed Episodes passed the ordinary Agent verdict but failed the
  context-free compliance probe: `j5-cancel-autopay-pending` repetitions 1
  and 2, and `j1-card-switch-stale-options` repetition 2.
- No failed or interrupted identity was rerun into the denominator.

The admitted ordinal-1 synthesized cell passed **3/3** fresh Episodes. Each
passed its ordinary Agent verdict and all five production
simulator-compliance criteria, including the vacuous
`simulator_complication_evidence` ruling for Complication `none`.

## Failure attribution

The three completed curated failures were calibration-context failures, not
criterion regressions. The context-free probe did not give the compliance
Judge the Scenario Goal or supplied Fixture knowledge:

- For `j5-cancel-autopay-pending`, the Judge could not establish that the
  customer's $875.20 payment was a real pending AutoPay payment. It therefore
  failed both `simulator_factual_grounding` and
  `simulator_complication_evidence`.
- For `j1-card-switch-stale-options`, the Judge treated the customer's
  correction from remaining statement balance to statement balance as an
  invented balance claim and failed `simulator_factual_grounding`.
  `simulator_complication_evidence` passed in the original ruling.

All five same-transcript complete-context rejudges passed: the three completed
denominator failures and the two corresponding non-denominator diagnostics.
These rejudges did not regenerate simulator behavior or replace any Episode in
the 32/39 first-pass denominator.

The four interrupted identities were rerun only under `diagnostics/`. Two
passed the context-free probe. The card-switch and false-premise diagnostics
reproduced the context-free failures and then passed same-transcript
complete-context rejudging, corroborating the attribution above.

## Decision

This run is rejected as landing evidence. Its honest first pass remains 32/39:
the missing Scenario context, unattributed interruption, exhausted credit, and
same-family simulator/Judge pairing prevent it from qualifying as the requested
gate. The diagnostics still support the infrastructure attribution, but they do
not turn the run into a pass or authorize landing the wording.

Machine-readable counts are in `summary.json`; complete-context results are in
`contextual-rejudge/summary.json`.
