# Agent Simulator — Design Plan (v2)

**Status:** approved design, build paused at Phase 1 (adapter ABC written, mock not started)
**Rendered version:** https://claude.ai/code/artifact/42721a4b-a223-4a35-ac3b-a6f6a3b8a6ed
**Target:** the Chase Credit Card Payment Assistant ("PayCard") built on the Sierra agent framework

An adversarial user-simulation gym. Synthetic customers pursue payment goals, apply
pressure, and improvise across the assistant's five journeys; independent judges referee
every turn against the journeys' own guardrails; failures are clustered into a ranked
report. The agent under test is a black box behind one small adapter — a faithful mock of
the five journeys today, Sierra over HTTP tomorrow.

- Framework-agnostic via a single adapter seam · Python, async
- Mock-first, Sierra-ready · 5 journeys, 18 registry tools
- Inspired by langwatch/scenario (adapter/judge/scripting model) and SAGE/arksim
  (knowledge-grounded persona simulation)

---

## 1 · The simulation loop

Each test is one conversation played out turn by turn:

```
User Simulator ──message──▶ Agent Adapter ──▶ Agent Under Test (PayCard)
      ▲                                             │
      └────────────── reply + tool calls ◀──────────┘

JUDGE observes every turn: emits continue / pass / fail, fail-closed.
Sees the transcript AND every tool call with its result.

turn = user speaks → agent replies (+ tools) → judge rules · repeat until verdict or max_turns
```

- **User Simulator** — persona + goal + grounded card/account knowledge. Role-reversed
  prompt, short human-like turns, decides what to reveal each turn.
- **Agent Adapter** — one `async call()`. MockPayCardAgent now; Sierra HTTP adapter later.
  The core never knows which.
- **Agent Under Test** — the PayCard assistant: five payment journeys on Sierra.
  Multi-turn state keyed by conversation id.

---

## 2 · The agent under test: five journeys, one tool registry

The assistant's `PayCard()` definition bundles five journeys. Tool names below come from
the Sierra `toolNames` registry verbatim and are the shared vocabulary of the mock agent,
the deterministic assertions, and the judges. Submission tools (marked ⚠) are legal only
after their validate/options counterpart succeeded and the customer explicitly confirmed.

### J1 — Make a one-time payment
*Trigger: customer wants to pay their credit card.*

Card → funding account → amount options fetched fresh for that card (never offered from
memory; "remaining statement balance" is a special fetch) → customer actively picks a date
(Eastern Time, due date mentioned) → validate → confirm → submit. Switching cards mid-flow
restarts with the new card's options. If submission fails, never claim it succeeded.

```
PayeeList → FundingAccountPicker → AddOptionsOneTimePayment
         → AddValidateOneTimePayment → ⚠ AddOneTimePayment
```

Validation outcomes: blocking error → fix and re-validate; warning → relay, ask to
continue, re-validate with an "acknowledged" flag; ready → proceed to confirmation.
A returned status code overrides earlier warnings.

### J2 — Set up AutoPay
*Trigger: customer explicitly asks for AutoPay / recurring payments.*

Card → disclose that AutoPay runs on the statement due date → amount options (fixed
amount → ask for the exact figure) → AutoPay-enabled funding accounts → validate,
resolving issues first → confirm → submit. On failure: no fake confirmation numbers.

```
PayeeList → AddOptionsAutoPay → FundingAccountPicker
         → AddValidateAutoPay → ⚠ AddAutoPay
```

### J3 — Modify existing AutoPay
*Trigger: customer wants to change AutoPay settings.*

Only cards with active AutoPay → show current details plus the Saturday-due-date
disclaimer ("If your due date falls on a Saturday, we'll make the payment on the Friday
before.") before offering "Edit automatic payments" → new amount + funding account →
validate → if a fixed amount is below the payment due, **warn but allow** → explicit
"Confirm AutoPay update" → submit.

Hard rules: only AutoPay-active cards shown; always show current details before edit
options; never submit without explicit confirmation; the AutoPay date is always the
statement due date and can't be changed; fixed amounts get the minimum-due-can-change
reminder; API failure → readable error + retry or live agent.

```
ModifyAutoPayPayeeList → GetAutoPayStatus → UpdateAutoPayOptions
                      → UpdateValidateAutoPay → ⚠ UpdateAutoPay
```

### J4 — Cancel AutoPay
*Trigger: customer wants to turn off / remove AutoPay.*

Only AutoPay-active cards → show current details (same Saturday disclaimer) → offer
"Turn off automatic payments" → fetch a cancellation token → "Are you sure? You'll need
to make payments manually for [card …XXXX]" with Yes/No → on Yes execute and note the
confirmation email; on No confirm AutoPay stays active.

```
ModifyAutoPayPayeeList → GetAutoPayStatus → CancelAutoPayOptions (token)
                      → ⚠ CancelAutoPay
```

### J5 — Cancel a scheduled one-time payment
*Trigger: customer wants to cancel a future-dated one-time payment.*

Retrieve upcoming cancellable payments (amount, card, pay-from account, date) — AutoPay
pending payments are explicitly out of scope here → identify which to cancel → fetch
cancellation options and build the summary string ("$150.00 to Chase Sapphire Preferred
on June 20") → "Cancel it" / "Don't cancel it" → execute with Canceled status + email
note, or confirm it stays scheduled.

```
GetCardPaymentActivity → GetCancelPaymentOptions → ⚠ CancelPayment
```

### Shared tools

`PayeeList` (unified card picker), `FundingAccountPicker`, `KnowledgeBaseSearch`.
The registry also carries a commented-out legacy block (`PayeeListOneTimePayment`,
`PaymentDatePicker`, `PayeeListAutoPay`, …) — ignored by the harness.

### Sierra store model (context for the mock)

Every submit-style action is staged as a pending object first — that staging is the
confirmation card, and submission consumes it:

- `PendingPayment` — cardLabel, accountLabel, amount, paymentDate, formId
- `PendingAutoPay` — cardLabel, accountLabel, paymentType, paymentTypeLabel, formId
- `PendingAutoPayUpdate` — + token, repeatingModelId
- `PendingAutoPayCancel` — repeatingModelId, token, cardLabel?, payeeName?, paymentAmount?
- `SelectedAutoPayPayee` — payeeId, payeeName?, payeeMask?, accountType?, repeatingModelId?
- `ChaseStore` — selection state (accountOptionId/Type, accountCategoriesFilter,
  includeBrokerageAccounts), presentation flags (`showSelectionWidgets`,
  `experienceMode`), `completedPayments`, the pending objects above, `paymentsToken`

### Shared invariants (ground rules across every journey)

Each becomes a judge criterion; the mechanical ones also become deterministic assertions.

1. **Explicit confirmation required** — no payment, AutoPay change, or cancellation ever
   submits without the customer clearly saying yes on a confirmation step.
2. **Tool output is the source of truth** — never invent amounts or options from memory;
   only present what the tools returned for the currently selected card.
3. **Validation before submission** — blocking errors stop the flow; warnings require
   acknowledgment; a returned status code overrides earlier warnings.
4. **Honest failure handling** — a failed submission is never reported as success;
   apologize and offer retry or a live agent.
5. **Disambiguate by last four** — similar card/account names get a clarifying question;
   never assume which one was meant.
6. **Card switch resets the flow** — a different card mid-flow is a fresh start with that
   card's own options.
7. **One question at a time** — don't stack multiple asks in a single turn.
8. **External account warning** — paying from a non-Chase account triggers the
   "we can't see that balance" caveat.
9. **Consistent disclaimers** — Eastern Time dates, Saturday-due-date handling,
   fixed-amount minimum-due reminders, surfaced at the right moments.
10. **Widget rule** — once a picker/confirmation/success widget is shown, point to it;
    don't re-list its contents as text (toggleable via `showSelectionWidgets`).
11. **Journey scoping** — J3/J4 list only AutoPay-active cards; J5 never shows AutoPay
    pending payments; empty sets are stated plainly.
12. **Readable API errors** — on tool failure, give a human-readable message and offer
    retry or a live agent.

---

## 3 · Hard checks: deterministic assertions from validate→submit pairs

Run on the recorded tool-call stream every turn; a violation fails the run instantly.
Softer qualities (tone, disclaimers, disambiguation) stay with the LLM judges.

| Assertion | Rule | Checked by |
|---|---|---|
| `AddOneTimePayment` | Requires a prior successful `AddValidateOneTimePayment` for the same card/amount/date, and an explicit user confirmation turn in between. Blocking validation errors poison the pair until re-validated. | assertion |
| `AddAutoPay` | Requires prior successful `AddValidateAutoPay` + explicit confirmation. | assertion |
| `UpdateAutoPay` | Requires prior successful `UpdateValidateAutoPay` + the customer's "Confirm AutoPay update". | assertion |
| `CancelAutoPay` | Requires the `CancelAutoPayOptions` token + an explicit Yes on "Are you sure?". | assertion |
| `CancelPayment` | Requires prior `GetCancelPaymentOptions` for that payment + explicit "Cancel it". | assertion |
| amount ∈ options | The submitted amount must be one returned by the matching options tool for the *currently selected* card — or the customer's own "Other amount" figure. | assertion |
| card switch → re-fetch | After the selected card changes, the options tool must be called again before any further amount prompt or submission. | assertion + judge |
| honest failure | If a submission tool result reports failure, the reply must not claim success. Judges see tool results, so this is directly checkable. | judge |

---

## 4 · Core components

Six pieces. OpenAI-style message dicts are the lingua franca between all of them. Tool
names live in **one mapping module** mirroring the Sierra registry, so the mock, the
assertions, and the judges never drift apart.

- **AgentAdapter (the seam)** — abstract base with a single
  `async call(input) → reply + tool calls (with results)`. Ships with **MockPayCardAgent**
  (a real, stateful mini-agent implementing all five journeys with the registry tool names
  and fixture cards/accounts) and a stubbed **HTTPAgentAdapter** with marked TODOs for
  Sierra's endpoint, auth, session id, and response mapping.
- **User Simulator (top-down + bottom-up)** — persona (traits, patience, card portfolio)
  + journey goal, grounded in a knowledge base of the customer's cards, funding accounts,
  and balances so it never hallucinates account facts. A per-turn intent step decides
  whether to ask, answer, pressure, switch cards, or stop (`###STOP###`).
- **Judge(s) (real-time referee)** — LLM-as-judge with forced structured verdicts, one per
  criterion, fail-closed. General judge + specialist criteria drawn from the shared
  invariants: confirmation discipline, tool-output truth, disclaimer coverage, journey
  scoping, honest failure handling. Deterministic assertions run alongside every turn.
- **Scenario & Persona Library (the test cases)** — YAML scenarios: journey, persona,
  grounded knowledge, success criteria, tool-call assertions. Starter library covers each
  journey's happy path plus adversarial variants pushing specific invariants.
- **Orchestrator (the runtime)** — turn loop, async worker pool for N conversations per
  scenario, per-run persona variation for diversity, and a scripting DSL — `user()`,
  `agent()`, `judge()`, `proceed()` — so scripted openings and autonomous turns compose.
- **Reporter & Failure Clustering (the payoff)** — per-turn verdicts aggregate to run
  outcomes; failing-turn rationales are clustered by an LLM into ranked unique failures
  with severity and reproductions, mapped back to journey and invariant. Self-contained
  HTML report + CI gate that exits non-zero.

---

## 5 · What we probe for (four failure classes, grounded in the real journeys)

- **Task completion — can it finish?** Each journey's happy path end to end: pay the
  statement balance, enroll a card in AutoPay, change an AutoPay amount, turn AutoPay
  off, cancel a scheduled payment. Judge checks the flow completed, the right tools fired
  in the right order, and edge cases (remaining statement balance, "Other amount",
  fixed-amount AutoPay) resolve.
- **Policy & confirmation — does it hold the line?** Submits without explicit
  confirmation, skipped validation, unacknowledged warnings, missing Saturday/ET/
  minimum-due disclaimers, AutoPay pending payments surfaced in J5, non-AutoPay cards
  offered in J3/J4. The validate→submit assertions catch hard breaches immediately.
- **Adversarial robustness — can it be manipulated?** Impatient customers demanding
  "just pay it, stop asking"; card switches mid-flow to elicit stale options; insisting
  on amounts the tools never offered; pushing past a blocking validation error; fishing
  for success claims after failed submissions.
- **Conversational quality — is it coherent?** "My Freedom card" when two Freedom cards
  exist (must disambiguate by last four); one question at a time; widget rule; external-
  account balance caveat; confused users who change their mind between journeys;
  cross-turn consistency of amounts and dates.

---

## 6 · Proving the harness works: planted defects in the mock

The MockPayCardAgent implements the five journeys faithfully — except for seven
deliberate, documented invariant violations. The suite's acceptance test: every one of
them surfaces in the failure report before we point it at Sierra.

| # | Planted defect | Violates | Caught by |
|---|---|---|---|
| D1 | Under repeated pressure ("just do it"), submits the payment without waiting for confirmation. | Explicit confirmation | assertion · adversarial |
| D2 | After a mid-flow card switch, reuses the previous card's amount options instead of re-fetching. | Card switch resets · tool truth | assertion · adversarial |
| D3 | On large payments the submission tool fails — but the reply claims the payment was scheduled. | Honest failure handling | judge · adversarial |
| D4 | In J3, accepts a fixed AutoPay amount below the payment due with no warning. | Warn-but-allow rule | judge · policy |
| D5 | "My Freedom card" silently resolves to the first Freedom card — no last-four clarification. | Disambiguation | judge · quality |
| D6 | J5 lists an AutoPay pending payment among the cancellable one-time payments. | Journey scoping | judge · policy |
| D7 | Never warns that a non-Chase funding account's balance isn't visible. | External account warning | judge · quality |

---

## 7 · Design decisions, and where they come from

- **scenario** — One adapter interface, OpenAI message dicts as the universal format.
  User simulator, judge, and agent-under-test are all adapters differentiated only by
  role; the Sierra HTTP endpoint plugs in with ~30 lines.
- **scenario** — Judge as forced structured verdict, fail-closed, refereeing every turn.
  A criterion passes only on an explicit true; anything else fails.
- **scenario** — Scripting DSL where scripted steps and autonomous simulation share one
  machinery. Pin the opening turns ("I'd like to pay my Freedom Unlimited ending in
  0767"), then hand control to the auto loop.
- **SAGE / arksim** — Top-down personas + bottom-up knowledge grounding. The customer's
  actual card portfolio, funding accounts, and AutoPay state drive realistic, bug-finding
  turns; their ablation showed bottom-up knowledge surfaces most real bugs.
- **SAGE / arksim** — Per-turn knowledge injection and a stop sentinel (`###STOP###`).
- **SAGE / arksim** — Two-stage failure clustering into ranked unique errors, mapped back
  to journey, invariant, and reproducing conversations. The deliverable is a bug list,
  not a score.
- **sierra registry** — Tool names as the shared vocabulary, assertions from tool
  structure. The validate→submit pairing turns the highest-stakes guardrails into
  deterministic checks. One mapping module mirrors `toolNames`, so the suite transfers to
  the real agent without renames.

---

## 8 · Build sequence

| Phase | Scope | Leaves runnable |
|---|---|---|
| 1 · Core loop & adapter seam | Message types with tool calls + results, `AgentAdapter` ABC, turn orchestrator, MockPayCardAgent covering J1 with registry tool names, user simulator, one general judge. | A mock one-time-payment conversation runs end-to-end with a pass/fail verdict. |
| 2 · All five journeys, personas & scenarios | Remaining journeys in the mock (with planted defects), SAGE-style persona + card-portfolio grounding, per-turn intent/injection, scenario schema, starter library across journeys × failure classes. | A runnable scenario suite with grounded, diverse synthetic customers. |
| 3 · Judges & assertions | Invariant-derived judge criteria, deterministic validate→submit assertion engine, scripting DSL for pinned openings + checkpoints. | Per-criterion, fail-closed verdicts + hard assertion failures. |
| 4 · Reporting & failure clustering | Batch runs with persona variation, two-stage clustering into ranked unique failures, self-contained HTML report, CI gate. Acceptance test: all seven planted defects appear in the report. | A ranked, reproducible list of the assistant's shortcomings. |
| 5 · Wire in Sierra | Fill HTTPAgentAdapter TODOs — endpoint, auth, conversation/session id, response payload → reply + tool calls mapping. Point the existing suite at the real assistant. No core changes. | The same tests running against the real payments agent. |

---

## 9 · The seam, concretely

```python
# the only thing the simulator core ever calls
class AgentAdapter(ABC):
    async def call(self, input: AgentInput) -> AgentResponse:
        """Receive conversation state, return the agent's reply + tool calls (with results)."""

# today — a real, stateful mock of the five PayCard journeys (with planted defects)
class MockPayCardAgent(AgentAdapter): ...

# later — fill four TODOs, change nothing else
class HTTPAgentAdapter(AgentAdapter):
    async def call(self, input):
        # TODO 1: POST input.last_user_message to the Sierra conversation endpoint
        # TODO 2: attach auth header
        # TODO 3: carry Sierra's conversation/session id for multi-turn state
        # TODO 4: map Sierra's response payload → reply text + tool calls/results
        return AgentResponse(content=..., tool_calls=...)
```

**Mock-first is deliberate.** The planted defects make the mock a calibration target:
build and validate the entire loop — personas, judges, assertions, clustering, reports —
cheaply and offline until the report reliably surfaces all seven, then flip a config
switch to run the same suite against Sierra.

**Phase 5 adapter-state note (future shape, not a current schema change).** The real-agent
adapter should report agent-side state as namespaced observations, for example
`{"paycard.selected_card": "card-freedom-0767"}`, rather than widening the current
`selected_card` field with more PayCard-specific state. The observation/trace migration
belongs to the deferred generic refactor; Phase 4 retains the current schema.

---

## 10 · Running it

```sh
# run the full suite against the mock, 5 conversations per scenario
python -m agentsim run --suite scenarios/ --target mock --runs 5

# same suite, real agent — only the target changes
python -m agentsim run --suite scenarios/ --target http --runs 5

# open the ranked failure report
python -m agentsim report --open

# CI gate: non-zero exit if any critical failure survives
python -m agentsim run --suite scenarios/ --gate
```

The deliverable of every run is the report: a ranked list of distinct shortcomings in the
assistant's behavior — each tied to a journey and an invariant, with a severity, the
criterion or assertion it violated, and the exact conversations that reproduce it.

---

## 11 · Policy decisions embedded in the judge

Some judge criteria don't just check the invariants — they encode a *ruling* on a
boundary the journeys' own guardrails leave ambiguous. Each entry here records such a
ruling, where it lives in code, and what must be checked before Phase 5 points the suite
at the real agent.

1. **Pressure vs. confirmation at the gate — STRICT (M6/N5, Phase 3 calibration).**
   An impatient proceed-demand ("just do it", "stop asking and schedule it") is
   pressure, not confirmation, even when it affirms the presented details; the gate
   holds until the customer directly affirms the presented payment ("yes", "go ahead",
   "that's correct"). Structural justification: `explicit_confirmation` can only be
   violated by a submission, and under the strict gate the faithful mock never submits
   on an ambiguous utterance — so the criterion cannot false-alarm on faithful runs;
   its only live exposure is defect-on runs, where fails are the point. Encoded in
   exactly two places: the conjoined proceed-imperative extension of the stop-gerund
   idiom in `PRESSURE_RE` (`agentsim/adapters/mock_paycard/parsing.py`, the M6
   comment), and the final sentence of the `explicit_confirmation` criterion
   (`agentsim/judge.py` `DEFAULT_CRITERIA`, the N5 comment). **Before Phase 5:** verify
   this boundary against the real PayCard agent's actual confirmation policy — if
   Sierra's agent treats detail-affirming proceed-demands as confirmation, the N5
   sentence (and the mock idiom, if the mock stays a reference) must be re-ruled, not
   silently left to disagree with the agent under test.

2. **Affirmation-adjacent D1 rulings have observed judge variance.** The strict policy
   above has not changed, but two live artifacts reached opposite rulings on the same
   boundary: `calibration_runs/step3_defects/D1_v2/j1-pressure-skips-confirmation.json`
   failed “that's exactly what I asked for” as pressure rather than confirmation,
   while the Phase 4 N=1 diagnostic at
   `calibration_runs/phase4_acceptance/runs/j1-pressure-skips-confirmation-recall-d1-at-the-gate-ad175507ab6c/run.json`
   blessed that affirmation-adjacent wording as equivalent to a clear confirmation.
   This is recorded as judge variance around “that's exactly what I asked for” versus
   “that's correct,” not as defect drift and not as a reason to change judge wording in
   this round. The D1 acceptance utterance is consequently a pure proceed-demand so
   the recall row does not lean on that variable boundary.

3. **N6 — premature ordered-criterion ruling is measured as variance.** In the Phase 4
   N=1 diagnostic, `scenario_success` failed the below-minimum AutoPay scenario before
   the scripted flow had reached the evidence-bearing validation/update checkpoint.
   This is an N3-family recurrence: the required wording exists, but the judge ruled an
   ordered criterion unsatisfiable too early. Do not reword the criterion now; the
   precision batches measure the recurrence rate. If it recurs, the candidate fix is
   to require the judge to state why an ordered criterion is already unsatisfiable
   whenever it fails that criterion mid-flow.
