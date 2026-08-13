# Phase 3 Build Plan

Scope: design doc §8 Phase 3 — the deterministic assertion engine, per-invariant
specialist judge criteria, and the scripting DSL — under amendments 13–18 (stated in
the Phase 3 kickoff instructions; they continue Phase 1–2's amendments 1–12 and
override the design doc where they differ).

Done = (a) the assertion engine runs over Trace artifacts only, with D1-on and D2-on
tripping their assertions deterministically offline and all-flags-off happy paths
producing zero assertion failures; (b) all twelve §2 invariants exist as criteria —
four already live in the calibration-validated DEFAULT_CRITERIA, the rest as
trigger-conditioned specialists batched into the existing single per-turn judge call;
(c) user()/agent()/judge()/proceed() scripts run through the same orchestrator and
produce the same Trace; (d) the offline suite is green and the new judge wording is
live-verified calibration-style: 13/13 defects-off pass with zero noise, plus
defect-on spot runs failing with the right source (amendment 16).

## File tree

```
agentsim/
  registry.py            CHANGE  add SUBMIT_PAIRINGS: per submit tool, the structured
                         metadata the engine needs (validate/options counterpart —
                         subsuming VALIDATE_FOR_SUBMIT — the options tool for the
                         journey, which argument keys must match between validate and
                         submit (formId primary; payeeId/amount/paymentDate/token
                         fallback), and where the form/token id lives in the validate
                         RESULT). Stays the one mapping module: the engine gets no
                         literal tool names of its own.
  assertions.py          NEW  the deterministic engine (amendment 13): pure Python,
                         no LLM, input = Trace (+ the scenario's must_not_call list),
                         never engine or mock internals. AssertionEngine.check(trace)
                         -> AssertionReport{failures: [AssertionFailure], degraded:
                         [which checks could not fully run and why]}. Stateless and
                         prefix-safe: the orchestrator calls it on the trace-so-far
                         after every agent turn; Phase 4/5 call the same method on
                         deserialized full traces. Checks (closed set):
                         - validated_submit — for each of the five §3 pairings: the
                           LAST counterpart call before the submit must exist, be for
                           the same payment (formId/token match via SUBMIT_PAIRINGS,
                           argument-fields fallback), and have result status "ready"/
                           success — a blocking-error or warning status poisons the
                           pair until a later successful re-validate; and a user turn
                           must exist strictly between the validate-carrying agent
                           turn and the submit-carrying agent turn (D1-on violates
                           this: validate + submit in one agent turn). Whether that
                           user turn is a genuine confirmation stays with the judge
                           (amendment 4/13).
                         - amount_in_options — every J1 validate/submit amount ∈ the
                           amounts in the most recent options RESULT for that payeeId,
                           OR appears verbatim as a dollar figure in a user turn after
                           that options fetch (the customer's own "Other amount");
                           J2/J3 payment types ∈ the option ids of their options
                           result. Requires results (see trace.py note below).
                         - refetch_after_card_switch — when TraceTurn.selected_card
                           changes between agent turns (both non-None), no further
                           validate/submit until the journey's options tool has been
                           called again at or after the switch turn (D2-on violates:
                           validate follows the switch with no re-fetch).
                         - must_not_call — any call to a scenario-forbidden tool.
                         Degraded mode (amendment 18): each check declares what it
                         needs; missing results skip only the status/options-content
                         checks (recorded in report.degraded, structured), ordering
                         checks still run; missing selected_card skips the switch
                         check; nothing ever raises on a sparse trace.
  criteria.py            NEW  the twelve §2 invariants as criteria (amendment 15):
                         invariants 1/2/4 (+ goal completion) stay exactly the four
                         calibration-validated DEFAULT_CRITERIA — wording untouched.
                         The rest become SpecialistCriterion = Criterion + a trigger
                         predicate Trace -> bool (pure Python; fixtures usable as
                         static reference data only):
                         - warning_acknowledged (inv 3, judge half): trigger = a
                           validate result with status "warning" in the trace
                           (exactly the N3 fix — active only once the warning exists)
                         - card_disambiguation (inv 5): trigger = a user turn names a
                           card token shared by ≥2 fixture cards with no last-four
                         - card_switch_reset (inv 6, judge half — stale text amounts):
                           trigger = selected_card changed mid-journey
                         - one_question_at_a_time (inv 7): always active
                         - external_account_caveat (inv 8): trigger = an account the
                           FundingAccountPicker result marks type "external" appears
                           in validate/submit arguments or is selected in the flow
                         - required_disclaimers (inv 9): three narrow triggers —
                           Saturday disclaimer when GetAutoPayStatus ran and its
                           nextPaymentDate is a Saturday; ET-dates when J1 date
                           collection is in play; minimum-due-can-change when a
                           fixed-amount AutoPay validate occurred
                         - widget_rule (inv 10): trigger = a widget indicator in tool
                           results — never fires against the mock (doesn't model
                           widgets); written now so Phase 5 gets it for free
                         - journey_scoping (inv 11): trigger = ModifyAutoPayPayeeList
                           or GetCardPaymentActivity ran (grade only-active-cards /
                           no-AutoPay-pendings against those results)
                         - readable_api_errors (inv 12): trigger = any tool result
                           with a failure status
                         Every description passes the amendment 16 checklist:
                         end-state phrased; trigger-conditioned on trace evidence;
                         "violated only when it can no longer be satisfied"; required
                         disclosures/disclaimers and grounded out-of-scope
                         explanations are never "invented" content (N1–N3 are the
                         cautionary examples). active_criteria(trace) returns the
                         turn's specialist set.
  script.py              NEW  scripting DSL (amendment 17): step constructors user(),
                         agent(), judge(), proceed() returning plain dataclasses
                         (UserStep{text|None}, AgentStep, JudgeStep,
                         ProceedStep{turns|None}) — data, not closures, each with
                         to_dict/from_dict, so Phase 4 can mechanically emit a replay
                         script from a recorded trace's turn list (user(text) per
                         user turn) without new machinery. validate_script() rejects
                         malformed sequences with named positions.
  types.py               CHANGE  FailureRecord dataclass (amendment 14): source
                         ("assertion"|"judge"), id (assertion type or criterion_id),
                         turn_index, message, data (structured extras: tool names,
                         expected vs actual) + to_dict. Verdict types stay here,
                         outside the trace, as before.
  judge.py               CHANGE  GeneralJudge gains an optional dynamic_criteria
                         hook (Trace -> extra criteria appended per call); the
                         fail-closed path iterates the criteria actually sent that
                         turn. DEFAULT_CRITERIA wording untouched; one batched LLM
                         call per turn stays the invariant (amendment 15).
  orchestrator.py        CHANGE  (1) optional assertions=AssertionEngine|None param
                         (None = Phase 1/2 behavior, tests unmodified): after every
                         agent turn the engine checks the trace-so-far BEFORE the
                         judge call; any failure fails the run immediately without
                         spending that turn's judge call — the hard gate of
                         amendment 14. (2) optional script= param: scripted steps
                         consume the same turn loop — user(text) injects the message
                         (trace intent "scripted"), user() delegates to the
                         simulator, assertions still run every agent turn, the judge
                         runs only at explicit judge() checkpoints while scripted,
                         and proceed() hands over to the autonomous loop (simulator +
                         per-turn judge) under the shared max_turns budget. One
                         machinery, one Trace shape. (3) RunResult gains failures:
                         list[FailureRecord] merging assertion and judge failures
                         with sources; outcome derivation: any assertion failure →
                         fail regardless of judge decisions.
  scenario.py            CHANGE  build_assertions(scenario) — engine with the
                         scenario's must_not_call entries; run_scenario wires it plus
                         the specialist criteria (build_judge composes
                         DEFAULT_CRITERIA + scenario_success (wording untouched) +
                         active_criteria as the dynamic hook). tool_assertions schema
                         unchanged: validated_submit / amount_in_options /
                         refetch_after_card_switch entries stay valid but are
                         documentation — those checks are built-in and always on
                         (see decisions); only must_not_call adds behavior.
  trace.py               CHANGE  docstring only: move "amount ∈ options" to the
                         results-required list (the options result is the only place
                         the options exist; the calls-only claim was wrong). The
                         degraded behavior in assertions.py follows this corrected
                         docstring. No schema change; schema_version stays 1.0.

scripts/
  run_calibration.py     CHANGE  print/serialize RunResult.failures (source-tagged),
                         and add --defect FLAG so the live defect-on spot runs
                         (step 8 below) can run a scenario against a deviant mock.

tests/
  test_assertions.py     NEW  hand-built Trace objects (incl. deserialized-from-JSON)
                         for unit edges: happy pairing passes; missing counterpart,
                         warning/blocking status poisoning until re-validate,
                         same-turn validate+submit (no user turn between), amount not
                         in options, "Other amount" from a user turn passes,
                         refetch-after-switch, must_not_call; degraded traces —
                         results stripped, selected_card None — skip the right checks
                         and report them in degraded, never raise.
  test_assertions_defects.py  NEW  amendment 18, mock-driven with no LLM (MockDriver
                         builds real traces): D1 on → validated_submit trips
                         deterministically; D2 on → refetch_after_card_switch trips;
                         all flags off across all five journeys' happy paths → zero
                         assertion failures.
  test_criteria.py       NEW  trigger predicates unit-tested on real mock traces:
                         each specialist activates exactly on its trigger (Saturday
                         status → disclaimer criterion active; external account in
                         play → caveat active; warning validate → warn-ack active;
                         happy J1 trace → neither) and the composed judge call
                         carries DEFAULT + scenario_success + only the active set.
  test_judge.py          CHANGE  add: dynamic hook criteria included in schema/
                         prompt and fail-closed over the per-turn set; existing
                         tests pass unmodified.
  test_script.py         NEW  DSL: validate_script errors; scripted opening produces
                         the same Trace shape as autonomous turns; judge only at
                         judge() checkpoints; proceed() hands off to the simulator;
                         step dataclasses JSON round-trip; a script mechanically
                         built from a recorded trace's user turns replays against
                         the mock and reproduces the tool-call sequence (the Phase 4
                         replay contract, proven now).
  test_orchestrator.py   CHANGE  add: assertion hard gate (engine failure → fail
                         even when the stub judge says pass/continue; failure
                         sources recorded); assertions=None preserves old behavior.
  test_scenario.py       CHANGE  add: run_scenario wires engine + specialists;
                         must_not_call from YAML reaches the engine; existing tests
                         pass unmodified.
```

Unchanged: clock.py, llm.py, simulator.py, adapters/ (mock untouched — Phase 3 adds
no mock behavior), fixtures/, the 13 scenario YAMLs (schema already carries the
vocabulary), test_calibration_regressions.py, test_live_smoke.py.

## Components & key decisions

1. **Built-in vs YAML-selected assertions.** The five validate→submit pairings,
   amount ∈ options, and refetch-after-switch are invariants of the agent, not of a
   scenario — the engine always runs them on every trace (amendment 13 lists them
   unconditionally and reserves only must_not_call as "the scenario's"). The YAML
   vocabulary is unchanged for compatibility; its first three types are now
   documentation of what a scenario targets. Only must_not_call feeds the engine.

2. **Assertions run first, judge second, per turn.** Deterministic checks are free;
   on an assertion failure the run fails immediately and that turn's judge call is
   skipped — the source is unambiguous and amendment 14's hard gate is structural
   (an assertion failure can never be outvoted because the judge never rules on that
   turn). Judge criterion failures become FailureRecords too, so Phase 4 clustering
   keys on {source, id, turn_index, data} uniformly.

3. **Pairing identity via SUBMIT_PAIRINGS metadata.** The mock (and Sierra's store)
   thread formId/token from validate result to submit arguments — that is the
   primary same-payment match; argument-field overlap (payeeId/amount/paymentDate)
   is the fallback when results are absent (degraded mode drops the status check but
   keeps ordering + the user-turn-between check). All metadata lives in registry.py
   so the engine, mock, and judges still share one vocabulary module.

4. **Trigger computation is trace-grounded, fixtures as reference only.** Triggers
   read tool results recorded in the trace (FundingAccountPicker's type field,
   GetAutoPayStatus's nextPaymentDate, validate statuses) plus static fixture name
   tables for the card-tie trigger — never mock state. So the same triggers work on
   Phase 5 HTTP traces; triggers whose evidence is absent simply never activate
   (fail-quiet, matching degraded assertions).

5. **Specialists don't touch validated wording.** DEFAULT_CRITERIA and the
   scenario_success wrapper keep their committed, live-verified text. New specialist
   descriptions are written to the amendment 16 checklist and get their own live
   verification (step 8) before Phase 3 is called done. M5 remains the reference
   case: goal_completion (general) catches it, amount_in_options (assertion) must
   pass it — asserted in test_assertions_defects.py against the M5 regression
   utterance.

6. **Scripted and autonomous turns share one loop.** script= is interpreted inside
   run_conversation, not by a second runner: same trace appends, same assertion
   cadence, same outcome derivation. While scripted, the judge fires only at
   judge() checkpoints (pinned openings shouldn't spend LLM calls being refereed
   turn-by-turn); proceed() restores the per-turn judge. Steps are serializable
   dataclasses so a Phase 4 replay emitter is a trivial map over a trace's user
   turns — designed for, not built.

7. **Live verification (amendment 16), calibration-script style.** After the
   offline suite is green: (a) full 13-scenario defects-off run with specialists +
   engine active → expected 13/13 pass, zero assertion failures, zero judge noise;
   (b) defect-on spot runs via --defect for the judge-caught defects — D4
   (warning_acknowledged), D5 (card_disambiguation), D6 (journey_scoping), D7
   (external_account_caveat) → fail citing that specialist; D1/D2 defect-on → fail
   with source=assertion before any judge ruling; D3 already fails on the committed
   honest_failure wording. Artifacts to calibration_runs/step3*/; any noise mode
   found gets the N1–N3 treatment (reword, re-verify) before Phase 3 is done.

## Build order (tests alongside each step)

1. types.py FailureRecord + registry.py SUBMIT_PAIRINGS (+ trace.py docstring fix)
2. assertions.py + test_assertions.py (hand-built + degraded traces)
3. test_assertions_defects.py (D1/D2 on trip; all-off happy paths clean; M5 utterance
   passes amount_in_options)
4. orchestrator assertion gate + FailureRecord merge + test_orchestrator additions
5. criteria.py + test_criteria.py + judge.py dynamic hook + test_judge additions
6. scenario.py wiring (build_assertions, specialist hook) + test_scenario additions
7. script.py + orchestrator script support + test_script.py
8. run_calibration.py changes + live verification per decision 7; reword-and-rerun
   loop if needed → Phase 3 exit

## Notably out of scope

Batch runs, persona variation, failure clustering, HTML report, CI gate, and the
replay-script *emitter* (Phase 4 — only its contract is proven by test_script.py);
HTTPAgentAdapter (Phase 5); YAML exposure of scripts; widget modeling in the mock;
cross-journey mind-change scenarios; any mock behavior change.
