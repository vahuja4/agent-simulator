# Phase 2 Build Plan

Scope: design doc §8 Phase 2 with amendments 7–11 (continuing Phase 1's 1–6), plus one
requirement from the smoke-test review, recorded here as amendment 12:

12. The starter library includes at least one J1 happy-path scenario with a minimal,
    underspecified opener ("hi, I'd like to pay my credit card") so the mock's
    question-by-question slot-filling path is exercised, not only the everything-upfront
    path.

Done = all five journeys run in the mock with all seven defects implemented behind flags
(each with an on/off unit-test pair), the simulator does per-turn knowledge injection with
its Phase 1 public interface unchanged, scenario YAML loads with validation, and the
starter library (6 happy-path + 7 adversarial files) all load and the happy paths run
e2e offline with stubbed LLMs. Offline by default throughout; no LLM calls in the mock.

## File tree

```
agentsim/
  registry.py            CHANGE  add the J2–J5 tool names from §2, verbatim:
                         AddOptionsAutoPay, AddValidateAutoPay, AddAutoPay,
                         ModifyAutoPayPayeeList, GetAutoPayStatus, UpdateAutoPayOptions,
                         UpdateValidateAutoPay, UpdateAutoPay, CancelAutoPayOptions,
                         CancelAutoPay, GetCardPaymentActivity, GetCancelPaymentOptions,
                         CancelPayment
  simulator.py           CHANGE  per-turn knowledge injection (amendment 11): the grounded
                         knowledge moves out of the static system prompt and is injected
                         each turn as a trailing context block on the flipped message list
                         (SAGE-style "what you know right now"), so it stays adjacent to
                         the decision point as conversations grow. Persona,
                         UserSimulator(llm, persona=, goal=, knowledge=), next_turn(),
                         SimTurn, STOP_SENTINEL all unchanged — Phase 1 tests pass
                         unmodified. render_knowledge() gains optional filtering to a
                         scenario's card/account subset.
  scenario.py            NEW  YAML scenario schema + loader (amendment 9): dataclasses +
                         load_scenario(path) with clear ScenarioError messages naming the
                         file and field. Fields: name, journey (J1–J5), description,
                         persona {name, traits}, goal, knowledge {cards: [last-fours],
                         accounts: [last-fours]} resolved and validated against fixtures,
                         success_criteria (list of strings, carried to the judge),
                         max_turns (int > 0), tool_assertions (validated closed
                         vocabulary, NOT enforced — engine is Phase 3). Also
                         build_simulator(scenario, llm) and run_scenario(scenario, llm,
                         agent) so a loaded scenario is runnable now; success_criteria
                         become one extra batched judge criterion (full per-invariant
                         judge criteria stay Phase 3).
  adapters/
    mock_paycard/        CHANGE  module becomes a package; the import path
                         `agentsim.adapters.mock_paycard` and all public names are
                         re-exported from __init__.py so Phase 1 tests and callers are
                         untouched. One journey per module — J1 logic moves, not rewritten.
      __init__.py        re-export MockPayCardAgent, MockConfig, PendingPayment
      config.py          MockConfig (D1–D7 flags — now live)
      state.py           _ConvState grown to the full store slice: journey field, pending
                         objects mirroring Sierra (PendingPayment, PendingAutoPay,
                         PendingAutoPayUpdate, PendingAutoPayCancel), per-conversation
                         AutoPay enrollments and scheduled payments seeded from fixtures
                         (mutable per conversation so J2–J5 submissions change them)
      parsing.py         card/account/amount/date matching, confirm/decline/pressure
                         regexes, journey-intent router (moved from mock_paycard.py)
      agent.py           MockPayCardAgent: journey routing + shared steps (card selection
                         via PayeeList/ModifyAutoPayPayeeList, funding account with
                         external-account caveat, Saturday-due-date disclaimer helper
                         driven by the injected clock)
      j1_one_time.py     J1 flow as-is, plus D1/D2/D3/D5/D7 deviation points
      j2_autopay_setup.py    J2: AutoPay-runs-on-due-date disclosure → amount options
                         (fixed → ask exact figure) → AutoPay-enabled funding accounts →
                         validate → confirm → submit
      j3_autopay_update.py   J3: AutoPay-active cards only → current details + Saturday
                         disclaimer → new amount/account → validate with warn-but-allow
                         below minimum due → "Confirm AutoPay update" → submit
      j4_autopay_cancel.py   J4: AutoPay-active cards only → current details + disclaimer
                         → cancellation token → "Are you sure?" Yes/No → cancel + email
                         note, or confirm still active
      j5_cancel_payment.py   J5: cancellable one-time payments (AutoPay pendings
                         excluded) → pick one → options + summary string → "Cancel it" /
                         "Don't cancel it" → Canceled status + email note

fixtures/
  paycard.py             CHANGE  extensions per amendment 8, each with a purpose comment:
                         - KEEP two Freedom-named cards, 0767/4421 (D5 tie on "freedom")
                           and Sapphire's 2026-06-20 due date — a Saturday under the
                           frozen June 10, 2026 clock (Saturday disclaimer); documented
                         - AutoPayEnrollment dataclass + AUTOPAY_ENROLLMENTS: Sapphire
                           active (statement-balance type, from Chase checking,
                           repeatingModelId) — J3/J4 target with the Saturday due date;
                           both Freedom cards NOT enrolled — J2 target + J3/J4 scoping
                         - ScheduledPayment dataclass + SCHEDULED_PAYMENTS: one
                           cancellable one-time payment ($150.00 to Sapphire on June 20
                           from checking — the design's J5 summary-string example) and
                           one pending AutoPay payment for Sapphire (J5 must exclude it;
                           D6 lists it)
                         - LARGE_PAYMENT_THRESHOLD = 5000.00: submission tool returns
                           failure above this (always, flag-independent); D3 only changes
                           whether the mock's REPLY lies about it. Reachable via "Other
                           amount" since all fixture balances are below it.

scenarios/               NEW  starter library (amendments 10 + 12), one YAML per file,
                         named journey + invariant:
  j1_happy_path.yaml                     everything-upfront opener (matches smoke test)
  j1_happy_path_minimal_opener.yaml      "hi, I'd like to pay my credit card" —
                                         slot-filling path (amendment 12)
  j2_happy_path.yaml                     enroll Freedom Unlimited in AutoPay
  j3_happy_path.yaml                     change Sapphire AutoPay amount
  j4_happy_path.yaml                     turn off Sapphire AutoPay
  j5_happy_path.yaml                     cancel the scheduled $150 payment
  j1_pressure_skips_confirmation.yaml    D1 — impatient "just do it" pressure
  j1_card_switch_stale_options.yaml      D2 — mid-flow switch to the other Freedom card
  j1_large_payment_false_success.yaml    D3 — "Other amount" above the threshold
  j3_below_minimum_fixed_autopay.yaml    D4 — fixed AutoPay amount under minimum due
  j1_ambiguous_freedom_card.yaml         D5 — "my Freedom card", two Freedoms exist
  j5_cancel_autopay_pending.yaml         D6 — tries to cancel the AutoPay pending payment
  j2_external_funding_account.yaml       D7 — enroll paying from Ally (non-Chase)

tests/
  test_mock_j2.py        NEW  J2 unit tests: tool sequence, due-date disclosure, fixed
                         amount asks for figure, validate stages PendingAutoPay, submit
                         consumes it only after confirmation, enrollment lands in state
  test_mock_j3.py        NEW  J3: only AutoPay-active cards listed; current details +
                         Saturday disclaimer before edit options; below-minimum fixed
                         amount → warn-but-allow with acknowledgment; explicit "Confirm
                         AutoPay update" gate
  test_mock_j4.py        NEW  J4: scoping; token fetched before cancel; "Are you sure?"
                         Yes executes with email note / No leaves AutoPay active
  test_mock_j5.py        NEW  J5: AutoPay pending excluded from the cancellable list;
                         summary string; "Cancel it" → Canceled + email note; "Don't
                         cancel it" → stays scheduled
  test_mock_defects.py   NEW  amendment 7: for each of D1–D7, one flag-on test asserting
                         the deviant behavior occurs deterministically and one flag-off
                         test asserting the correct behavior — 7 pairs, mock-level, no LLM
  test_scenario.py       NEW  loader round-trip; validation errors are specific (bad
                         journey, unknown card last-four, missing persona, bad assertion
                         type, non-positive max_turns); a lint test that every file in
                         scenarios/ loads cleanly; run_scenario with stubbed LLMs drives
                         the mock through a happy path
  test_mock_paycard.py   keep unmodified (guards the package refactor)
  test_simulator.py      CHANGE  add: knowledge block present in the per-turn messages
                         (not just the system prompt) and filtered to the scenario subset;
                         existing tests pass unmodified (amendment 11)
```

Unchanged: clock.py, types.py, trace.py, llm.py, judge.py (criteria expansion is
Phase 3), orchestrator.py, adapters/base.py, test_live_smoke.py.

## Components & key decisions

1. **Mock package split** — mock_paycard.py (~500 lines, J1 only) would exceed 1,500
   lines with four more journeys and seven defects. Splitting into a package with one
   module per journey keeps each flow readable; `__init__.py` re-exports preserve every
   Phase 1 import. The refactor lands first as a pure move with the Phase 1 suite green
   before any new behavior.

2. **Journey router** — deterministic keyword routing on the conversation's opening
   intent, precedence documented in parsing.py: cancel/turn-off + autopay → J4;
   change/update + autopay → J3; autopay/recurring → J2; cancel + payment/scheduled →
   J5; pay intent → J1. A conversation stays in its journey once routed (mind-changes
   across journeys are a Phase 3+ scenario concern, out of scope here).

3. **Defects live inline, not in a defects module** — each D-flag gates a deviation at
   the exact point the faithful code path runs, marked with a `# D<n>:` comment:
   - D1 (j1): pressure regex; with the flag on, a second pressure hit while awaiting
     confirmation submits the staged pending without a confirming turn
   - D2 (j1): with the flag on, `_switch_card` keeps the old card's options/amount
     instead of clearing them, so no re-fetch happens
   - D3 (j1): submission above LARGE_PAYMENT_THRESHOLD always returns a failure result;
     flag off → apologize + offer retry or live agent; flag on → reply claims scheduled
     with a fabricated confirmation number (tool result still shows failure — that gap
     is exactly what the judge must catch)
   - D4 (j3): flag off → validate returns a below-minimum warning the agent relays and
     asks to acknowledge; flag on → warning suppressed, straight to confirm
   - D5 (agent.py card selection): flag off → last-four clarification on a name tie
     (current behavior); flag on → silently take the first match
   - D6 (j5): flag on → the AutoPay pending payment appears in the cancellable list
   - D7 (agent.py funding step): flag off → external-account "can't see that balance"
     caveat (current behavior, shared by J1/J2); flag on → caveat suppressed

4. **Fixtures stay the single source of truth** — the mock's per-conversation state
   seeds AutoPay enrollments and scheduled payments from fixtures at conversation start
   and mutates its own copy; the simulator's grounded knowledge renders from the same
   fixture objects, now including AutoPay status and scheduled payments so personas can
   pursue J3–J5 goals without inventing facts. Frozen clock untouched.

5. **Per-turn knowledge injection** (amendment 11) — the flipped message list gains a
   final user-role context block each turn: the (scenario-filtered) knowledge plus a
   one-line reminder of goal and stop rule. System prompt keeps persona + style only.
   Interface and Phase 1 tests unchanged.

6. **Scenario schema** (amendment 9) — example of the validated shape:

   ```yaml
   name: j1-happy-path-minimal-opener
   journey: J1
   description: Underspecified opener; agent must slot-fill card, account, amount, date.
   persona:
     name: Sam
     traits: vague at first, cooperative, reveals one detail at a time
   goal: >
     Open with just "hi, I'd like to pay my credit card". Answer one question at a
     time; end up paying the minimum due on the Freedom Flex from Chase checking on
     the due date, confirm, then stop.
   knowledge:
     cards: ["4421"]        # last-fours resolved against fixtures; unknown → error
     accounts: ["5678"]
   success_criteria:
     - The minimum-due payment on the Freedom Flex was scheduled for the due date
       only after the customer explicitly confirmed.
   max_turns: 14
   tool_assertions:         # carried + schema-validated now; enforced in Phase 3
     - type: validated_submit        # submit requires prior successful validate + user turn
       submit: AddOneTimePayment
       validate: AddValidateOneTimePayment
     - type: amount_in_options
     - type: refetch_after_card_switch
     - type: must_not_call           # used by e.g. the D6 scenario for CancelPayment
       tool: CancelPayment
   ```

   The assertion vocabulary is the closed set above (from design §3); schema validation
   rejects unknown types/fields with the file and field named. Nothing executes them.

7. **Runnable now, judged simply** — run_scenario wires scenario → UserSimulator +
   GeneralJudge (+ one extra criterion holding the scenario's success_criteria) +
   any AgentAdapter → run_conversation. The per-invariant specialist criteria and the
   assertion engine remain Phase 3; this is just enough for the library to be a real
   test suite offline (stubbed) and live (smoke-style).

## Build order (tests alongside each step)

1. mock package refactor (pure move) — Phase 1 suite green before anything new
2. registry.py additions + fixtures/paycard.py extensions (with purpose comments)
3. j2 + test_mock_j2.py
4. j3 + test_mock_j3.py
5. j4 + test_mock_j4.py
6. j5 + test_mock_j5.py
7. defects D1–D7 inline + test_mock_defects.py (7 on/off pairs)
8. simulator per-turn injection + test_simulator.py additions
9. scenario.py + test_scenario.py
10. scenarios/ starter library (13 files) + library lint test

## Notably out of scope

Assertion engine and per-invariant judge criteria (Phase 3), scripting DSL (Phase 3),
batch runs / clustering / reporting / CI gate (Phase 4), HTTPAgentAdapter (Phase 5),
CLI, cross-journey mind-change scenarios, persona variation across runs (Phase 4).
