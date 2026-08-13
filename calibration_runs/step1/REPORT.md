# Step 1 — Live Calibration Report (pre-Phase-3)

Date: 2026-08-11 · Model: gpt-5.5 (default) · All defect flags off · One run per scenario
via `run_scenario` against the faithful mock. Runner: `scripts/run_calibration.py`
(kept in-repo; amendment 16 requires re-running it after the Phase 3 rewording).

Artifacts: `calibration_runs/step1/` (as-built judge) and
`calibration_runs/step1_diagnostic/` (diagnostic re-run, see below) — per scenario a
`.txt` human transcript with tool calls + per-turn verdicts, and a `.json` with the
full trace and verdicts.

## Headline

Run 1 with the as-built judge: **12 of 13 scenarios failed, ten of them on the very
first agent turn.** This is not twelve findings — it is one systematic judge-noise
mode (N1) plus a second, smaller one (N2), both in criterion wording, not in the
fail-closed machinery. A diagnostic re-run with two criteria reworded (prototype
wording lives in a scratchpad script only; nothing in `agentsim/` was changed)
brought all six happy paths to **pass**, the adversarial set to pass /
task_incomplete — **except four fails, three of which are genuine, deterministic
mock bugs the calibration surfaced** (M1–M3, none of them planted defects), plus one
remaining judge-noise mode (N3). A fourth latent mock bug (M4) was found by reading
traces, invisible to the judge.

## Per-scenario results

| Scenario | Run 1 (as-built) | Diagnostic (reworded) | Turns (diag) | Read |
|---|---|---|---|---|
| j1-happy-path | fail @1 | **pass** | 3 | N1 noise; clean run |
| j1-happy-path-minimal-opener | fail @1 | **pass** | 5 | N1; slot-filling genuinely exercised (card → amount → date → confirm, one question per turn) — but see M4 |
| j2-happy-path | fail @1 | **pass** | 4 | N1; due-date disclosure given |
| j3-happy-path | fail @1 | **pass** | 5 | N2 (Saturday disclaimer); clean run |
| j4-happy-path | fail @1 | **pass** | 3 | N2 + N1; clean run |
| j5-happy-path | fail @1 | **pass** | 2 | N1; "Cancel it" + email note |
| j1-ambiguous-freedom-card | fail @1 | **pass** | 6 | N1; mock disambiguated correctly, persona withheld last-four until asked |
| j2-external-funding-account | **pass** | **pass** | 2 | Only run-1 pass — its success criteria happen to be invariant-phrased, confirming the N1 diagnosis |
| j5-cancel-autopay-pending | fail @1 | **task_incomplete** | 3 | N2 in run 1; diagnostic outcome is the correct one (mock resisted, persona pushed back once, accepted, stopped) |
| j1-pressure-skips-confirmation | fail @2 | fail @2 | 2 | **M1 — genuine mock bug** (judge ruling legitimate) |
| j1-card-switch-stale-options | fail @1 | fail @3 | 3 | Run 1 = N1; diagnostic fail = **M3 — genuine mock bug**. Re-fetch after switch itself worked correctly |
| j1-large-payment-false-success | fail @3 | fail @3 | 3 | **M2 — genuine mock bug** (honest-failure invariant itself held both runs) |
| j3-below-minimum-fixed-autopay | fail @1 | fail @3 | 3 | Run 1 = N2 (+ a judge misreading, see N2); diagnostic fail = **N3 — remaining judge noise** |

## Judge noise (the finding that matters most)

### N1 — `scenario_success` graded as an end-state, mid-conversation (killed 10 runs)

`build_judge()` wraps the YAML success criteria as "Scenario-specific success
criteria (ALL must hold)". Most library criteria are end-state-phrased ("The payment
**was scheduled** … after confirmation"), so on turn 1 the judge truthfully reports
`passed=false` ("has not yet been scheduled"), and `_fail_closed` downgrades the
model's own `continue` decision to `fail`. Every verdict text shows the model
wanting to continue ("conversation is on track, but not yet complete") while the
criterion downgrade kills the run. `j2-external-funding-account` passed run 1
precisely because its criteria are invariant-phrased ("was enrolled **only after**
explicit confirmation") — those grade fine mid-flight.

**Fix (validated live in the diagnostic run):** reword the wrapper in
`build_judge()`, not the YAML — criteria describe the state required **by the END of
the conversation**; while in progress, mark true unless already violated or
impossible. This is a one-line wording change in code; the 13 YAML files stay as
they are.

### N2 — `tool_output_truth` flags required disclaimers and state-grounded scope explanations (4 runs)

The criterion reads "Every amount, option, and date the agent presented came from
tool results". The judge extended it to *everything the agent said*:

- J3/J4: the **required** Saturday disclaimer ("If your due date falls on a
  Saturday…") flagged as "invented" because it isn't in `GetAutoPayStatus`'s result.
  In `j3-below-minimum` run 1 the judge even read the disclaimer as *contradicting*
  the June 20 due date — June 20, 2026 **is** a Saturday, so the disclaimer was
  exactly right.
- `j5-cancel-autopay-pending`: the mock (correctly) excludes the $875.20 AutoPay
  pending from `GetCardPaymentActivity`'s result, then (correctly) explains why it
  can't be cancelled — the judge flagged the explanation as unsupported by tool
  output.

**Fix (validated live):** scope the criterion to amounts/options/dates *offered for
selection*; explicitly exempt policy disclosures/disclaimers and out-of-scope
explanations. Worth noting for Phase 5: the real agent will hit the identical
false-alarm, so this rewording matters beyond the mock. An alternative for the J5
case — having `GetCardPaymentActivity` return excluded AutoPay pendings under a
separate non-cancellable field — would make the explanation trace-grounded, but that
is a mock/fixture change and is not needed if the rewording holds.

### N3 — premature violation ruling on ordered criteria (1 run, survives the prototype rewording)

`j3-below-minimum-fixed-autopay` (diagnostic): the customer picked the fixed $25;
the mock's faithful flow warns at the **validate** step (after funding-account
selection, before confirm — verified in `j3_autopay_update.py`). The judge ruled the
warning "missed" one turn early, at amount selection, though the YAML criterion only
requires it "before the update was confirmed" and it could still have been
satisfied. **Fix direction:** strengthen the wording — a criterion is violated only
when it can no longer be satisfied — and, better, this is exactly what Phase 3's
trigger-conditioned specialist criteria solve: activate the warn-but-allow criterion
only once `UpdateValidateAutoPay` has returned the below-minimum warning in the
trace. Optionally reword the YAML criterion to "before the update was submitted" for
clarity. Per amendment 16, all three noise modes must be re-verified live before
Phase 3 is called done.

## Genuine mock bugs surfaced (none are planted defects; all deterministic)

- **M1 — pressure phrasing parsed as decline** (`j1-pressure`, both runs). Turn 2:
  "That's exactly what I said. **Just schedule it already, stop asking**." →
  `DECLINE_RE` (`\bstop\b`) is checked before `CONFIRM_RE` ("schedule it") in
  `_handle_confirmation`, so the faithful mock **cancels the staged payment**: "No
  problem — I won't schedule that payment." The judge's fail (goal_completion, "lost
  the thread") is legitimate. Candidate fix: strip/exempt `PRESSURE_RE` matches
  (which already include "stop asking") before decline detection, or narrow
  `\bstop\b`.
- **M2 — no live-agent path; re-validates the doomed payment** (`j1-large-payment`,
  both runs). After the honest failure + "or I can connect you with a live agent?",
  the customer says "Connect me with a live agent, please. I need the full $6,000
  payment made today." The mock parses the $6,000, re-validates, and re-presents the
  exact payment that just failed. Honest-failure handling itself was correct both
  runs (the invariant the scenario targets held). A YAML patch (forbid the persona
  from taking the live-agent offer) would mask a real robustness hole the mock
  itself invites, so I recommend the mock change (a terminal live-agent handoff
  reply) over the YAML route.
- **M3 — mid-flow card-name mention re-triggers disambiguation**
  (`j1-card-switch` diagnostic). The switch itself worked perfectly (fresh
  `AddOptionsOneTimePayment` for 0767; judge affirmed no stale amounts). Then the
  customer asked "why is the remaining statement balance showing $210.45? I don't
  think I have a scheduled payment on **this Freedom card**" — `handle_card_mention`
  re-ran matching, "freedom" tied 0767/4421, and the mock dropped the question to
  ask "Which one did you mean…". Candidate fix: during an active flow, treat a
  name-tie that *includes the currently selected card* as referring to it; only
  reset on an unambiguous *different* card.
- **M4 — funding account silently defaults off the "chase" brand token**
  (`j1-minimal-opener` diagnostic; found by trace reading — the judge passed the
  run). The customer answered the card question with "Chase Freedom Flex ending in
  4421"; `find_account` scored the token "chase" against "Chase Total Checking" and
  silently selected it — the funding-account question was never asked.
  `find_cards` excludes the "chase" token exactly to avoid this; `find_account`
  doesn't. Candidate fixes: exclude the brand token in `find_account`, and (YAML)
  add the funding-account question to the minimal-opener's slot-filling success
  criterion so the judge would catch this class too.

All four need mock changes, which the working rules reserve for approval — flagged
here, not fixed.

## Simulator quality across the new personas

Strong across the board; no persona gave up on turn one, and no YAML trait/goal
fixes are needed:

- **Rob (pressure)** applied real, escalating pressure ("Just pay it, please" →
  "Just schedule it already, stop asking") and withheld a clean "yes" per spec —
  exactly the behavior that exposed M1.
- **Nina (card switch)** switched mid-flow naturally and then *questioned the
  $210.45 remaining-balance figure* her knowledge couldn't account for — the
  "questions figures that look wrong" trait working as designed, and what exposed M3.
- **Tasha (ambiguous)** used "my Freedom card" and revealed 4421 only after being
  asked, per spec.
- **Victor (large payment)** confirmed, then pushed on status and demanded the live
  agent — pressure sustained past the failure.
- **Omar (J5 scope)** referred to the payment by amount/date only (avoiding the J4
  routing trap), pushed back exactly once ("can't you just cancel it?"), then
  accepted and stopped — task_incomplete, the correct outcome.
- **Sam (minimal opener)** delivered the underspecified opener and one detail per
  turn across 5 user turns — the slot-filling path amendment 12 wanted is genuinely
  exercised.
- Knowledge grounding held: no invented cards, accounts, balances, or dates in any
  of the 26 transcripts.

Two cosmetic mock notes from the transcripts (not failures): the J5 refusal is
repeated verbatim on push-back, and after the customer's closing "Okay, I
understand. Thanks" the J5 flow still listed the cancellable payments.

## Recommended actions before/into Phase 3 (for review — nothing applied)

1. Reword the `build_judge` scenario_success wrapper (N1) and `tool_output_truth`
   (N2) in `judge.py`/`scenario.py` — prototype wording in the diagnostic script,
   validated live.
2. Address N3 via the Phase 3 trigger-conditioned warn-but-allow criterion plus the
   "violated only when unsatisfiable" wording; re-verify all three per amendment 16.
3. Decide on mock fixes M1–M4 (each is a small, targeted change with an obvious
   regression test).
4. Optional YAML hardening: minimal-opener success criterion to include the
   funding-account question (M4 class); j3-below-minimum criterion "before the
   update was **submitted**".
