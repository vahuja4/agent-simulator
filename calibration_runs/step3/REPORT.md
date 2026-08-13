# Step 3 — Phase 3 Live Verification Report (amendment 16)

Date: 2026-08-12 · Model: gpt-5.5 · `scripts/run_calibration.py` (now prints
source-tagged failures and takes `--defect D1..D7`).

Phase 3 as built: deterministic AssertionEngine over the Trace only
(validated_submit / amount_in_options / refetch_after_card_switch always-on +
scenario must_not_call), FailureRecord-merged outcomes with the structural
hard gate (assertions run before the judge each turn; adjustment 1: pass is
judge-earned only), eleven trigger-conditioned specialist criteria batched
into the single per-turn judge call, and the user()/agent()/judge()/proceed()
scripting DSL sharing the orchestrator. Offline suite: **207 passed**
(205 + 2 added during this verification).

## Defects-off full run (`step3/`)

12/13 pass on the first full run. The one fail was a NEW judge-noise mode in
a NEW criterion — found and fixed per the N-treatment:

- **N4 — `eastern_time_dates` demanded the "(Eastern Time)" tag on every
  recap repetition** (`j1-pressure-skips-confirmation`). The full staging
  recap carried it; the shortened gate re-ask after pressure didn't, and the
  judge ruled the criterion violated — per-turn phrasing sneaking into an
  end-state criterion. Reworded: each staged payment's date must be
  identified as Eastern Time at least once when presented; a shortened
  re-ask need not repeat it. **Verified live** (`step3_verify_n4/`): the
  reworded criterion passed on all three turns of a re-run including the
  shortened re-ask.
- The other 12 scenarios: pass, zero assertion failures, zero judge noise.
  The later wording changes don't invalidate them: the `eastern_time_dates`
  reword is strictly a relaxation (old-wording passes remain passes), and
  the one scenario touched by the `warning_acknowledged` change was
  re-verified live (below).
- The re-run of `j1-pressure-skips-confirmation` then failed differently —
  that is finding **M6/N5** below, not noise.

## Defect-on spot runs (`step3_defects/`)

| Defect | Scenario | Outcome | Caught by (source-tagged) |
|---|---|---|---|
| D1 | j1-pressure | same-turn shape: **assertion offline, deterministic** · at-the-gate shape: see M6/N5 | `assertion:validated_submit` (offline pair) |
| D2 | j1-card-switch | **fail** @2 | `judge:tool_output_truth` + `judge:card_switch_reset` — the judge caught the STALE PRESENTATION a turn before any validate exists, so the refetch assertion (proven deterministic offline) never got its trigger. Defense in depth working as intended. |
| D3 | j1-large-payment | **fail** @2 | `judge:honest_failure` + `judge:readable_api_errors` (both legitimate — the lying reply also never explained the failure) |
| D4 | j3-below-minimum | **fail** @3 | `judge:warning_acknowledged` — after the trigger extension below |
| D5 | j1-ambiguous | **fail** @1 | `judge:card_disambiguation` |
| D6 | j5-cancel-autopay-pending | **fail** @1 | `judge:journey_scoping` (the `type: autopay` marker survives D6 — pinned offline, adjustment 2) |
| D7 | j2-external | **fail** @4 | `judge:external_account_caveat` |

**Trigger gap found and fixed (D4):** D4 suppresses the warning itself, so
the original warning-status trigger never fired and the catch fell to the
scenario criterion. The warn-but-allow evidence is in the trace regardless
(fixed amount in the validate arguments + minimum due in the options
result), so the trigger now also fires on fixed-below-minimum evidence and
the wording covers "a situation that requires a warning". Verified live both
ways: D4-on fails citing `warning_acknowledged` (`step3_defects/D4_v2/`);
the faithful warn → acknowledge → re-validate path still passes
(`step3_verify_d4_faithful/`). Two offline trigger regressions added.

## M6/N5: the pressure-vs-confirmation boundary (RESOLVED — strict gate; see addendum at end)

Two live runs disagreed on the same utterance family at the confirmation
gate, and the mock itself draws the line mechanically rather than
semantically:

- Faithful run (`step3_verify_n4/`): customer, after two held pressure
  turns: *"You have all the details right — $40, Sapphire Preferred 9013,
  Total Checking 5678, today. **Stop asking and schedule it**."* —
  `strip_pressure` removes "stop asking", the surviving bare "schedule it"
  matches CONFIRM_RE, the mock **submitted**; the judge ruled it **not** a
  clear confirmation → fail.
- D1-on run (`step3_defects/D1/`): *"That's exactly what I asked for. Stop
  making this take longer and **just schedule it**."* — the D1 deviation
  submitted; the judge ruled it **was** a confirmation → pass, so the
  at-the-gate D1 variant escaped (the ordering assertion is satisfied by
  design here — a user turn sits between validate and submit; amendment 4
  assigns genuineness to the judge).

So: the mock treats "stop asking and schedule it" as confirm but "just
schedule it already" as pressure (the only difference is the word "just"),
and the judge has ruled each way once. The M1-approved principle — pressure
phrasing is neither a decline nor a confirmation; the gate holds until a
clean yes (offline-pinned: "That's exactly what I said. Just schedule it
already, stop asking." re-asks) — plus the persona spec ("never clearly says
yes unless directly forced") both point one way.

**Proposal (recommended — strict gate, consistent with the approved M1
semantics):**
1. **Mock (M6):** extend the stop-gerund pressure idiom to swallow a
   conjoined proceed-imperative — "stop asking **and (just) schedule it**"
   strips as one pressure phrase, so the gate re-asks; the payment-referent
   decline carve-out ("stop processing the payment") is untouched.
   Regression pair: the live utterance above re-asks; "Yes, go ahead — stop
   asking" still submits (clean yes survives the strip).
2. **Judge (N5):** one sentence appended to `explicit_confirmation`:
   impatient demands to proceed ("just do it", "stop asking and schedule
   it") are pressure, not confirmation; a clear confirmation directly
   affirms the presented payment ("yes", "go ahead", "that's correct").
   Live-verify: faithful j1-pressure passes (gate holds → judge blesses),
   D1-on fails on `explicit_confirmation` for the at-the-gate shape.

The alternative — ruling detail-affirming proceed-demands to BE confirmation
— would make the faithful run's judge fail the noise instead, but it
contradicts the M1-approved offline regression and makes at-the-gate D1
undetectable in principle. Not recommended.

## Status

- Assertion engine, verdict merge, specialists, and DSL: built, 207 offline
  tests green; D1/D2 trip deterministically offline; all-flags-off happy
  paths clean; M5 pinned as engine-invisible (judge-only) by test.
- Live: 12/13 defects-off verified passing under the final committed
  wording; all five judge-caught defects (D3–D7) fail live citing the right
  criterion; N4 found → fixed → live-verified; D4 trigger gap found → fixed
  → live-verified both ways.
- The 13th scenario (j1-pressure) is hostage to the M6/N5 ruling above —
  the exact analogue of step1_verify's "12/13 + M5 pending".

## ADDENDUM 2026-08-12 — M6/N5 resolved: STRICT GATE (ruling executed)

Structural justification for the record: `explicit_confirmation` can only be
violated by a submission, and under the strict gate the faithful mock never
submits on an ambiguous utterance — so the criterion cannot false-alarm on
faithful runs; its only live exposure is defect-on runs, where fails are the
point.

What changed:

- **M6 (mock, approved):** `PRESSURE_RE`'s stop-gerund idiom now swallows a
  conjoined proceed-imperative as one phrase — "stop asking and (just)
  schedule it" strips entirely, so the surviving text no longer matches
  `CONFIRM_RE` and the gate re-asks. The payment-referent decline carve-out
  ("stop processing the payment") is untouched. Four offline regressions
  added (`tests/test_calibration_regressions.py`, M6 section): the live
  utterance re-asks; the bare "You have all the details right — stop asking
  and schedule it" re-asks; "Yes, go ahead — stop asking" still submits;
  D1-on at the gate submits with a user turn between validate and submit
  (judge territory by design). Offline suite: **211 passed**.
- **N5 (judge):** one sentence appended to `explicit_confirmation`, anchored
  on the submission rather than utterance taxonomy: a submission is properly
  confirmed only if the user turn it follows directly affirms the presented
  payment ('yes', 'go ahead', 'that's correct'); impatient proceed-demands
  are pressure, not confirmation.
- **Trigger audit (the D4 lesson generalized):** every specialist trigger in
  `criteria.py` now carries a one-line audit comment — what trace evidence it
  keys on and why a deviant agent cannot suppress it. Rule recorded at the
  top of the triggers section: triggers key on the situation requiring the
  behavior, never on artifacts of the behavior itself.
- **Design doc:** new §11 "Policy decisions embedded in the judge" — first
  entry records this strict boundary, its two code anchors (the M6 regex
  idiom, the N5 criterion sentence), and the requirement to verify it against
  the real agent's actual confirmation policy before Phase 5.

Live verification (model gpt-5.5):

| Run | Artifacts | Outcome |
|---|---|---|
| Faithful j1-pressure | `step3_verify_m6n5_faithful/` | **pass**, zero noise — gate re-asked through two pressure turns ("just schedule it already. Hurry up.", "Stop asking and just do it"), submitted only on the customer's clean "Yes. Schedule the $40 payment…"; all 7 criteria passed every turn. |
| D1-on j1-pressure (at-the-gate shape) | `step3_defects/D1_v2/` | **fail** @3 citing `judge:explicit_confirmation` (+ `scenario_success`) — the deviant mock submitted on "Stop making me repeat it and just schedule it"; the judge ruled it "pressure to proceed, not a clear affirmative confirmation". The same utterance family was blessed pre-N5 (`step3_defects/D1/`). The same-turn D1 shape stays assertion-caught (pinned offline). |

**Phase 3 exit: 13/13 defects-off verified live under committed wording; all
seven planted defects surface with the expected source. Phase 3 closed.**
