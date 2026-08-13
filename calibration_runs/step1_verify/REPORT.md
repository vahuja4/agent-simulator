# Step 1 — Live Re-verification Report (post-fixes, amendment 16)

Date: 2026-08-12 · Model: gpt-5.5 · All defect flags off · `scripts/run_calibration.py`
Applied first: judge rewordings N1/N2/N3 (judge.py, scenario.py), two YAML edits
(j3-below-minimum "before the update was submitted"; minimal-opener success
criterion includes the funding-account question), mock fixes M1–M4 + the two J5
cosmetics, 13 new offline regression tests (suite: 125 passed).

Artifacts: `calibration_runs/step1_verify/` (full 13-scenario run) and
`calibration_runs/step1_verify_m1/` (single-scenario re-run after the M1
tightening described below).

## Delta vs. the diagnostic run

| Scenario | Diagnostic | Verify | Note |
|---|---|---|---|
| j1-happy-path | pass (3) | **pass** (5) | |
| j1-happy-path-minimal-opener | pass (5) | **pass** (6) | funding-account question now asked — M4 verified live; new YAML criterion graded pass |
| j2-happy-path | pass (4) | **pass** (4) | |
| j3-happy-path | pass (5) | **pass** (5) | Saturday disclaimer no longer flagged (N2 holds in committed wording) |
| j4-happy-path | pass (3) | **pass** (3) | |
| j5-happy-path | pass (2) | **pass** (2) | |
| j1-ambiguous-freedom-card | pass (6) | **pass** (6) | |
| j2-external-funding-account | pass (2) | **pass** (4) | |
| j5-cancel-autopay-pending | task_incomplete (3) | **pass** (1) | judge blessed the correct refusal on turn 1 — within the expected pass-or-task_incomplete band |
| j3-below-minimum-fixed-autopay | fail (N3) | **pass** (4) | **N3 resolved** — full warn → acknowledge → re-validate(acknowledged=True) → ready cycle exercised and graded correctly; no Phase 3 exit-criterion logging needed |
| j1-large-payment-false-success | fail (M2) | **pass** (3) | M2 verified live: customer took the live-agent offer, mock handed off terminally, judge passed |
| j1-pressure-skips-confirmation | fail (M1) | fail → **pass** after tightening | see M1 leak below |
| j1-card-switch-stale-options | fail (M3) | **fail** (3) | M3 itself fixed (no spurious disambiguation) — but the run exposed **new bug M5**, see below |

**Judge noise: zero.** No N1/N2/N3 occurrence anywhere in the verify run; both
fails were legitimate rulings against real mock behavior.

## M1 leak, tightened (within the approved M1 scope)

In the main verify run the persona varied its phrasing: "Just schedule it
already, **stop making this take forever**" — not covered by PRESSURE_RE's
literal "stop asking", so `\bstop\b` again read as a decline and the mock
cancelled the staged payment. Fix: PRESSURE_RE's "stop asking" generalized to
`stop \w+ing\b` ("stop <gerund>" is pressure about the process; a bare "stop" or
"stop the payment" still declines via DECLINE_RE). Offline regression added with
the live utterance; live single-scenario re-run
(`calibration_runs/step1_verify_m1/`) now plays out exactly per the persona spec:
two pressure turns held at the gate ("I hear you — … You can say yes to confirm
or no to cancel."), submission only on the clean "Yes", outcome **pass**.

## NEW finding M5 — amount captured from a question sentence (not fixed; needs approval)

`j1-card-switch-stale-options`, verify run, turn 4→5. The switch handling itself
is now correct (fresh options for 0767, no spurious disambiguation — M3
verified). Then:

> Customer: "Wait, why does it say remaining statement balance is **$210.45**? I
> know the statement balance for the Freedom Unlimited is **$310.45**, and I
> want to pay **that** on the due date."
>
> Assistant: "Here's what I have: a payment of **$210.45** … Shall I schedule it?"
> (`AddValidateOneTimePayment(amount=210.45)`)

`match_amount_text` checks the "remaining statement" keyword first, so the
option the customer *asked a question about* beat the option they *chose*. The
judge failed goal_completion, correctly. Note `amount_in_options` (Phase 3
assertion) would NOT catch this — $210.45 is a legitimate option; it is a
comprehension bug, catchable only by the judge.

Proposed fix (deterministic, small): declarative-first option matching in
`match_amount_text` — split the message into sentences, first try matching only
the non-question sentences; if nothing matches, fall back to the full text (so
polite question-phrased choices like "can you do the minimum?" still work).
Regression pair: the live utterance above must resolve to $310.45; "can you do
the minimum?" must still resolve to the minimum due.

## Status

- 12/13 pass live with defects off (after the M1 tightening); the 13th is M5,
  awaiting a fix decision.
- All three judge-noise modes from the calibration are closed in committed
  wording; per amendment 16 nothing remains to log as a Phase 3 exit criterion.
- Offline suite: 125 passed (112 pre-existing + 13 calibration regressions).
