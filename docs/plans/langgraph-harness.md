# LangGraph synthesis harness — design note

Contract for sessions 02–09 on branch `codex/langgraph-synthesis-harness`.
Written 2026-09-21 (session 01), before any code existed. A session that must
deviate changes this note in the same commit and says so in its report.
Amended by session 03 (sections 4, 5, 8, 9, 11, 12).

HARNESS = `/Users/vishal/Desktop/agent_simulator-langgraph`, AGENT =
`/Users/vishal/Desktop/journey_agent`. The Journey is fictional appointment
rescheduling, `journey_id: appointment-rescheduling` (never a `J<n>` id). The
LangGraph agent stands in for a Sierra agent; nothing imitates Sierra's API.

This effort does not establish Judge accuracy, Sierra readiness, test quality,
coverage, Qualification or Admission. Every new Judge criterion, Assertion and
simulator instruction below is **designed, not empirically validated**.

## 0. Verified starting facts

- `AgentAdapter` has one `async call()`; no lifecycle. `run_conversation`
  builds the `Trace` per Turn, hard-gates on Assertions after every agent turn,
  and lets the Judge terminate the Episode. None of that works when tool
  evidence arrives only after the conversation, so the new loop is separate.
- `fixtures.paycard` is imported at module level by `agentsim/{scenario,simulator,criteria}.py`
  and `scenario_synthesis/{validator,generator,contracts,enumerate}.py` (the
  first pass missed the last two). Any `scenario_synthesis.*` import pulls it
  in through the package `__init__`. Free of it:
  `agentsim/{trace,types,judge,assertions,orchestrator,batch,clustering,report,llm}.py`.
- `cluster_failures` reads only `manifest.json` and clusters only
  `outcome == "fail"`. `BatchRunner` reads only `scenario.name` / `.source`
  and already records a raising run as `error`.
  `tests/test_phase4_imports.py` pins `batch.py`, `clustering.py`, `report.py`.
- `synthesized_scenarios/` is the Phase 4.5 lifecycle store (`library/` =
  admitted); `generated_scenarios/` is the Historical quarantine. Neither may
  receive this effort's output.
- The Judge and Simulated-user prompts hard-code payments wording.
- `gpt-5.6-luna` and `gpt-5.5` normalize to one family, and `agentsim/llm.py`
  holds a single shared OpenAI client (section 10).
- LangGraph docs (2026-09-21): `InMemorySaver` + `thread_id` for per-thread
  memory, sync `.invoke()`, `langchain.agents.create_agent` takes plain
  callables and a model instance (so a double is injectable). Section 3 needs
  no LangGraph API: the service records actions in its own tool layer.

## 1. Adapter lifecycle

A second interface. `AgentAdapter`, `ADAPTERS`, the mock and
`run_conversation` are untouched, so payments behavior cannot change.
`agentsim/adapters/conversation.py`:

```python
class ConversationAdapter(ABC):
    def start_conversation(self, *, fixture_state: FixtureState,
                           tool_failures: tuple[str, ...] = ()) -> ConversationHandle: ...
    def send_message(self, handle: ConversationHandle, text: str) -> AgentReply: ...
    def retrieve_trace(self, handle: ConversationHandle) -> RetrievedTrace: ...
    def release(self, handle: ConversationHandle) -> None: ...
```

- `ConversationHandle(conversation_id, fixture_state_sha256)`;
  `AgentReply(user_message_id, message_id, text)` — text only, no tool calls
  cross the adapter before the conversation ends;
  `RetrievedTrace(raw: dict | None, normalized: NormalizedTrace, error: str | None)`.
- `retrieve_trace` never raises for a service-side problem; it returns the gap.
  The others raise `AdapterError(kind, detail, status)`,
  `kind ∈ {transport, service, protocol}`.
- Synchronous (blocking `urllib`): execution is sequential by requirement.
- `agentsim/adapters/journey_service.py` alone knows the transport.
  `agentsim/adapters/__init__.py` is not edited.

## 2. Normalized Trace

New type in `agentsim/journey/normalized_trace.py`, `schema_version: "1.0"`.
`agentsim.trace.Trace` is not extended: it is the versioned payments contract.

```
NormalizedTrace
  schema_version, conversation_id, platform, fixture_state_sha256, tool_failures
  evidence: {messages: available|partial|unavailable,
             actions:  available|partial|unavailable, reasons: [str]}
  messages: [{message_id, sequence, role: user|agent, text}]
  actions:  [{action_id, sequence, tool_name, arguments: dict|None,
              result, result_available: bool, status: succeeded|failed|unknown,
              error: {code, message}|None,
              caused_by_message_id,      # the user message being handled
              reply_message_id}]         # the agent message that turn produced
```

- `sequence` is one counter across messages and actions: ordering is explicit.
- **Unavailable facts.** The normalizer copies and never infers. A missing
  field becomes `None` / `result_available: false` / `status: unknown`, its
  evidence class becomes `partial`, and a reason is appended. Status is never
  derived from a payload, nor references from ordering.
- Retrieval failed → `messages` come from the Transcript the harness recorded
  (real observations carrying the service's ids), `actions = []`,
  `evidence.actions = unavailable`. Raw messages that disagree with the
  Transcript → `evidence.messages = partial`.
- **Assertions** read `NormalizedTrace` directly.
- **Judge** reads `NormalizedTrace.to_trace() -> agentsim.trace.Trace`: one
  `TraceTurn` per message (`index` = position, so `FailureRecord.turn_index`
  maps to a `message_id`); each action is a `ToolCall` on the turn named by
  `reply_message_id` with `result = {"status", "output", "error"}`;
  `selected_card=None`. Defined only when both evidence classes are
  `available`; otherwise it raises — the Judge never sees a Trace with gaps.

## 3. Service operations (AGENT)

JSON over HTTP on `127.0.0.1`. AGENT: stdlib `ThreadingHTTPServer`; HARNESS:
`urllib.request`. Start:
`.venv/bin/python -m journey_agent.service --port 8765 --agent stub|langgraph`.

| Operation | Request | Success |
|---|---|---|
| start | `POST /conversations` `{"fixture_state": {...}, "tool_failures": [...]}` | `201 {"conversation_id", "fixture_state_sha256", "agent"}` |
| send | `POST /conversations/{id}/messages` `{"text"}` | `200 {"user_message_id", "reply": {"message_id", "text"}}` |
| retrieve | `POST /conversations/{id}/trace` | `200` raw Trace; seals the conversation; idempotent |
| release | `DELETE /conversations/{id}` | `204` |

Errors are `{"error": {"code", "message"}}`: `400 invalid_request`,
`404 unknown_conversation` (also anything after release),
`409 conversation_closed` (send after retrieve), `500 agent_error` (the user
message stays recorded, no reply exists, retrieve and release still work).

**Fixture state** travels inline in the start request and is deep-copied into
that conversation only. The service returns the SHA-256 of its canonical JSON
(`sort_keys=True, separators=(",", ":"), ensure_ascii=False`, UTF-8); the
adapter raises `AdapterError("protocol")` on mismatch. One source of truth, no
shared file, no import either way, isolation and reset by construction. AGENT
keeps a conforming fixture under `tests/` only.

**Controlled tool failure.** `tool_failures` lists tool names; the only
supported value is `"update_appointment"`. Such calls return `status: failed`,
`error.code: "update_failed"`, state unchanged.

**Tools** (names and these keys are contract; the rest is session 02's):
`lookup_appointments {customer_name?, confirmation_code?}` →
`{"appointments": [{"appointment_id", …}]}`; `find_available_slots
{appointment_id, …}` → `{"slots": [{"slot_id", …}]}`; `update_appointment
{appointment_id, slot_id}` → `{"appointment": {…}}`.

**Raw Trace**, recorded as things happen, identical for stub and LangGraph:

```json
{"trace_version": "1", "conversation_id": "…", "agent": "stub", "sealed": true,
 "fixture_state_sha256": "…", "tool_failures": [], "events": [
  {"seq": 1, "type": "message", "message_id": "m1", "role": "user", "text": "…"},
  {"seq": 2, "type": "action", "action_id": "a1", "tool_name": "lookup_appointments",
   "arguments": {}, "status": "succeeded", "result": {}, "error": null,
   "caused_by_message_id": "m1", "reply_message_id": "m2"},
  {"seq": 3, "type": "message", "message_id": "m2", "role": "agent", "text": "…"}]}
```

`reply_message_id` stays `null` if the agent raised before replying.

## 4. Journey inputs

HARNESS, `journeys/appointment_rescheduling/`, YAML, loaded by repository path.

`journey.yaml`: `schema_version`, `journey_id`, `title`, `agent_role` (one
phrase for the Simulated-user and Judge prompts), `tools`,
`permitted_behavior`, `required_rules: [{id, statement, checks}]` with checks
written `assertion:<id>` / `judge:<id>` (at least: identify the existing
appointment; explicit confirmation before changing it; report the update
result accurately, failure included), `valid_outcomes: [{id, description,
when: {tool_failures}}]` (`rescheduled`; `update_failed_reported`),
`criteria: {assertions, judge}`, `knowledge_rules: [{id, statement}]` (the ADR
0006 referents), `complications: {supported, unsupported: {id: reason}}`,
`max_turns_default`. Rules constrain the order of observable events only, so
alternative paths stay valid and nothing depends on the agent's workflow.

`fixture_state.yaml`: `schema_version`, `fixture_state_id`, `now` (frozen),
`customers: [{customer_id, name}]`, `appointments: [{appointment_id,
customer_id, confirmation_code, service, provider, start, status}]`,
`slots: [{slot_id, service, provider, start, available}]`. One customer has two
appointments for the same service (ambiguous reference needs it).

Strict loaders in `agentsim/journey/definition.py` (`JourneyDefinition`,
`FixtureState.sha256`, `load_journey_inputs(directory)`): unknown fields,
dangling ids and unknown check references fail loudly. Date-times are quoted
strings (an unquoted YAML timestamp cannot be hashed or sent inline), ids hold
no `.`, and `status ∈ {scheduled, completed, cancelled}`.
`JourneyDefinition.outcome_for(tool_failures)` derives the expected outcome;
`FixtureState.fact("<collection>.<id>.<field>")` resolves a grounded-fact path.

## 5. Criteria, Assertions and the Scenario seam

`agentsim/journey/checks.py` holds both halves by stable id; Journey files
reference ids only, so criterion text stays in code as
`agentsim.judge.Criterion` objects. Ids never reuse a payments id.

Assertions — pure functions of `NormalizedTrace` and the Scenario, returning
`passed | failed | unavailable`:

| id | checks |
|---|---|
| `update_targets_identified_appointment` | each update's `appointment_id` appeared in an earlier succeeded lookup result |
| `update_uses_offered_slot` | each update's `slot_id` appeared in an earlier succeeded slot-search result |
| `user_turn_before_update` | the update's `caused_by_message_id` is a user message later than the agent reply of the turn that first surfaced that slot (ordering only — the `validated_submit` split) |
| `update_matches_goal` | no succeeded update outside the Scenario's `appointment_id` / `target_slot_ids` |

"Each update" means every attempt, succeeded or failed; only
`update_matches_goal` is limited to succeeded ones. An Assertion is
`unavailable` when an evidence class it reads is not `available`, or when an
action, a referenced message or a contract result key it needs is missing.
`user_turn_before_update` also fails, with reason `slot_never_surfaced`, when
no earlier agent reply surfaced the slot.

`expected_outcome_evidenced` is a deterministic gate, not a failure source:
`rescheduled` needs a succeeded matching update; `update_failed_reported` needs
a failed matching update and no succeeded update at all ("matching" = the
Scenario's `appointment_id` and one of its `target_slot_ids`; a failed update
aimed elsewhere is not the expected outcome). It alone decides whether the
Goal was completed.

Judge criteria, end-state phrased for one final ruling:
`appointment_identified`, `reschedule_confirmed` (the user message before the
update is a clear yes to the presented change), `offered_slots_grounded`,
`update_result_reported_accurately` (Say/do consistency),
`reschedule_goal_completion`. Session 03 wrote the wording
(`agentsim/journey/checks.py`).

`reschedule_goal_completion` is pinned to the payments `goal_completion`
criterion in `agentsim/judge.py`: it is false only if the agent lost the
thread, contradicted itself, or made completion impossible. An unfinished Goal
alone does not fail it, and the criterion says so; completion is the gate's
call, not the Judge's. Otherwise every Turn-limit or gave-up Episode would
become `fail` through rule 5 of section 8, rule 7 would be unreachable, and
"running out of turns is not a policy failure" would break.

**Seam.** A parallel loader, `agentsim/journey/scenario.py`
(`JourneyScenario`, `load_journey_scenario`), exposing `name` and `source` so
`BatchRunSpec` accepts it. `agentsim/scenario.py` is not edited; its closed
`JOURNEYS` rejects the new files and the new loader rejects payments files.
The loader validates the file alone (schema, closed sets, check ids exist);
`check_against_inputs(scenario, journey, fixture_state)` checks fit against
the inputs it will run with — ids resolve and belong to the customer, target
slots are bookable and match the service, grounded facts equal Fixture state,
derived fields are what `journey.yaml` derives. Session 07 calls it and adds
the narrative Sealed-world check; `run` calls it before starting an Episode.
The three closed sets are restated in `agentsim/journey/` (importing
`scenario_synthesis.contracts` would pull in `fixtures.paycard`) and pinned
equal to the reviewed constants by tests.

**Simulated user.** `JourneySimulatedUser(UserSimulator)` in
`agentsim/journey/simulated_user.py` overrides `_system_prompt`,
`_turn_context` and `next_turn` (schema adds
`stop_reason: none|goal_achieved|gave_up`) and reuses `_flip`, `Persona`,
`SimTurn`. `agentsim/simulator.py` is not edited, so no payments instruction
changes. The confirmation-gate paragraph is copied verbatim and pinned equal
by a test. Knowledge text is rendered by code from grounded facts. It receives
Persona, Goal and knowledge only — never criteria or expected outcomes.

**Judge.** `JourneyJudge(GeneralJudge)` in `agentsim/journey/judge.py`
overrides only `_system_prompt` and `_render` (completed-conversation framing;
`agent_role`, Goal, required rules, criteria, transcript, projected Trace) and
inherits the schema, the single batched call and `_fail_closed`.

## 6. Synthesized Scenario schema and storage

```yaml
schema_version: 1
scenario_id: synth-appointment-rescheduling-<12 hex>
journey: appointment-rescheduling
description: …                        # model-written
persona: {archetype: cooperative, name: <fixture customer name>, traits: …}
goal: …                               # model-written
knowledge_level: low|medium|high
knowledge_evidence: {kind, rule|referent}
complication: none|…                  # exactly one of the nine
fixture: {customer_id, appointment_id, target_slot_ids, tool_failures}
grounded_facts: [{path: "appointments.A-1.start", value: …}]
max_turns: 12
expected_outcome: rescheduled         # derived in code
criteria: {assertions: […], judge: […]}       # derived in code
synthesis: {origin: synthesized, qualification: none, set_id, spec_id,
            journey_sha256, fixture_state_sha256, generation_config_sha256,
            generator_version, model, generated_at}
```

The model writes only `description`, `persona.traits` and `goal` (ADR 0007:
code owns structure and Fixture bindings). A response carrying any other field
is rejected with reason `model-supplied-derived-field` — never overridden.

```
synthesized_journey_scenarios/<journey_id>/<set_id>/
  provenance.json                    # input hashes, config, model, timestamp, counts
  accepted/<scenario_id>.yaml
  rejected/<spec_id>-<attempt>.json  # spec, raw model output, reason codes
```

Distinguishable from Curated by content (`synthesis.origin`), loader and
directory; its `synthesis` block is not a Phase 4.5 `SynthesisMetadata`, so
`load_synthesized_scenario` rejects it too. `qualification: none` says
validation is not Qualification or Admission.

## 7. Synthesis reuse

Module `scenario_synthesis/journey_synthesis.py` (keeps the direction
`scenario_synthesis → agentsim`; nothing in `agentsim` imports it today).

Reused: `contracts.py` constants `ARCHETYPE_IDS`, `COMPLICATION_IDS`,
`KNOWLEDGE_LEVELS` (imported; `load_reviewed_contracts` is not called);
`_strict.py` `_mapping`, `_strict`, `_positive_int`; `_async.py` `run`
(AGENTS.md single event loop); `evidence.py` `canonical_json`, `sha256_bytes`,
`sha256_file`, `utc_timestamp`, `atomic_json`, `atomic_text`; `agentsim/llm.py`
`LLMClient`, `OpenAILLM`, `LLMError`. `realization_provider.py` is followed in
shape (provider `Protocol`, deterministic stub, `validate_surface`-style
checks); its functions take a `CoverageBlueprint` and cannot be called.

Not reused: `blueprint`, `generator`, `validator`, `planner`, the legacy set
`enumerate` / `sample` / `compatibility`, `candidate`, `qualification`,
`ledger`, `completion`, `reporting`, `simulator_compliance`, `cli`,
`config.yaml`. No reviewed contract YAML is edited.

Flow: code plans `count` specs deterministically from variation settings and a
seed (appointment × archetype × Knowledge level × supported Complication ×
tool-failure condition, round-robin); derives `expected_outcome` and `criteria`
from `journey.yaml`; asks the model for three narrative fields; validates;
saves. Two attempts per spec, every failed one saved. A shortfall is printed
and exits non-zero. No coverage claim is made.

Validation: schema; closed sets; every fixture id resolves and belongs to the
Scenario's customer; target slots are available and match the appointment's
service; each grounded fact equals Fixture state; criterion references exist;
the narrative holds no identifier, code, date or time that is not a grounded
fact (Sealed-world rule).

Taxonomy: the nine Complications and three levels are the shared closed sets.
Applicability is declared in `journey.yaml`; all nine appear exactly once
across `supported` / `unsupported`. Proposed unsupported: goal shift and
multi-intent turn (two-Goal outcome derivation is not built — debt in the ADR
0004 BLOCKED sense, not an exclusion). The controlled tool failure is a
Fixture condition, not a Complication (ADR 0005).

## 8. Stop conditions and outcomes

Loop (`agentsim/journey/episode.py`): start → {Simulated user turn → append to
Transcript → `send_message` → append reply}* → retrieve → release. Retrieval
and release are attempted on every path. Nothing is judged or asserted during
the conversation. The agent has no end signal; claiming completion proves
nothing.

Stop reasons: `user_finished`, `user_gave_up`, `turn_limit`, `time_limit`
(300 s per Episode, checked between Turns; 60 s per HTTP request),
`adapter_error`, `simulator_error`.

Outcome — first matching rule (`agentsim/journey/evaluation.py`):

1. Stop reason `adapter_error` or `simulator_error` → `error`.
2. An evidence class not `available`, or an Assertion `unavailable` → `error`.
3. Any Assertion `failed` → `fail`; the Judge is not called, so cannot override.
4. Judge raises `LLMError` → `error`.
5. Judge decision `fail` (after `_fail_closed`) → `fail`.
6. Judge `pass` **and** `expected_outcome_evidenced` → `pass`.
7. Otherwise → `task_incomplete`.

So an Episode whose conduct is clean but whose outcome is not evidenced is
`task_incomplete`, whatever the stop reason.

`run_episode` and `evaluate_episode` are `async def`: the Simulated user and
the Judge are async. They run on `BatchRunner`'s loop, and the CLI enters
through the single process-local event loop (`scenario_synthesis/_async.py`).
The adapter stays blocking; with `concurrency=1` that is acceptable.

Each `FailureRecord` carries the check id, an explanation, and
`data = {stable details…, "evidence": {"message_ids", "action_ids", "files"}}`;
clustering similarity runs over `data`, so free text stays in `message`.
One Episode per Scenario (`seed=0`); no Pass rate over Seeds is reported.

## 9. Run directory and commands

The Run directory is a `BatchRunner` batch directory; the Episode directory is
its `runs/<run_key>/`:

```
journey_runs/<run_id>/
  manifest.json, clusters.json, report.md
  runs/<run_key>/
    scenario.yaml
    transcript.jsonl        # one line per message, flushed on arrival
    episode.json            # stop reason, timings, errors, service url, agent kind
    raw_trace.json          # untouched payload; absent if retrieval failed
    normalized_trace.json
    evaluation.json         # outcome, rule fired, Assertion results, Judge verdict, failures
    trace.json, transcript.md, run.json     # BatchRunner, from the RunResult
```

`async evaluate_episode(episode_dir, judge) -> EvaluationResult` with
`.to_run_result()` (an empty `Trace` when evidence is unavailable). `run`
passes `BatchRunner(concurrency=1)` an async `execute` = `await run_episode` +
`await evaluate_episode` (section 8). `summarize` calls `cluster_failures` unchanged (it
clusters `fail` only, so `error` never enters an agent-failure cluster), skips
`label_clusters`, lists `task_incomplete` by stop reason, and renders
`agentsim/journey/report.py`.

Entry point `scripts/journey_harness.py` (scripts are this repository's
composition roots; `run_calibration.py` already imports both packages):

```
.venv/bin/python scripts/journey_harness.py synthesize --journey journeys/appointment_rescheduling \
    --count 6 --set-id <set_id> [--seed 0] [--stub] [--output-root synthesized_journey_scenarios]
.venv/bin/python scripts/journey_harness.py run --scenarios <set dir> \
    --service-url http://127.0.0.1:8765 --run-id <run_id> [--output-root journey_runs]
.venv/bin/python scripts/journey_harness.py summarize journey_runs/<run_id>
```

`synthesize --stub` is a deterministic provider (precedent:
`StubRealizationProvider`). `run` has **no** doubles mode outside pytest — a
committed "pass" from a Judge double would read as a result — so session 09
relies on session 08's offline end-to-end test and commits only
`synthesize --stub` output as walkthrough evidence.

## 10. Model configuration

| Component | Setting |
|---|---|
| Judge | constant `gpt-5.5`; no flag or variable changes it |
| Simulated user | `AGENTSIM_SIMULATOR_MODEL` / `--simulator-model`, required |
| Synthesis generator | `AGENTSIM_SYNTHESIS_MODEL` / `--model`, required unless `--stub` |
| Harness credentials | `OPENAI_API_KEY` from the ignored `.env`, never printed |
| LangGraph agent | `JOURNEY_AGENT_MODEL` (`provider:model`) plus that provider's key; session 04 finalizes |

Missing configuration fails with one line before any network call.
`run --enforce-model-family-separation` (default off) uses
`agentsim.llm.models_share_family`. A **reported** live Run also needs a
Simulated-user model outside the `gpt-5` family — which the single shared
client cannot reach today; a second client is out of scope — a
Persona-fidelity spot-check of that model and of the new
`JourneySimulatedUser` instructions, and an explicit request.

## 11. File ownership

| # | Repo | Creates / edits |
|---|---|---|
| 02 | AGENT | `journey_agent/{fixture_state,tools,trace_recorder,service,stub_agent,agent_interface}.py`, tests, packaging |
| 03 | HARNESS | `journeys/appointment_rescheduling/*.yaml`; `agentsim/journey/{__init__,_strict,definition,normalized_trace,checks,scenario}.py`; `tests/test_journey_{definition,normalized_trace,checks,scenario}.py`; `tests/journey_trace_builder.py` (hand-built Traces and Scenarios, reusable by 05–08); `CONTEXT.md` (Journey definition, Expected outcome, Normalized Trace); `docs/solutions/journey-goal-completion-is-the-gates-call.md` |
| 04 | AGENT | `journey_agent/langgraph_agent.py`, model wiring, tests, pinned dependencies |
| 05 | HARNESS | `agentsim/adapters/{conversation,journey_service}.py`; `agentsim/journey/{simulated_user,episode}.py`; `tests/test_journey_{adapter,simulated_user,episode}.py`; `CONTEXT.md` |
| 06 | HARNESS | `agentsim/journey/{judge,evaluation}.py`; `tests/test_journey_evaluation.py` |
| 07 | HARNESS | `scenario_synthesis/journey_synthesis.py`; `tests/test_journey_synthesis.py`; `CONTEXT.md` |
| 08 | HARNESS | `scripts/journey_harness.py`; `agentsim/journey/report.py`; `tests/test_journey_{cli,report,e2e}.py` |
| 09 | both | setup-and-run docs, walkthrough evidence, final report |

Every HARNESS session also edits `ENVIRONMENT.md` and adds compound outputs.
Nobody edits `agentsim/{scenario,simulator,judge,criteria,assertions,orchestrator,trace,types,batch,clustering,report}.py`,
`agentsim/adapters/{__init__,base}.py`, the mock, `scenarios/` or reviewed
contracts.

Frictions in the README split, smallest fix each:

- 03 writes Assertions over a normalized Trace that 05 "produces". 03 owns the
  `NormalizedTrace` types and `to_trace()`; 05 owns only raw → normalized.
- 02 ‖ 03 both need Fixture state. Section 4's schema is the contract; 02
  writes its own conforming test fixture.
- 09's walkthrough assumes doubles outside pytest; section 9 provides none for
  `run`.
- `CONTEXT.md` is edited by 03 (Journey definition, Expected outcome,
  Normalized Trace), 05 (Agent adapter, Trace, Termination), 06 (Verdict: the
  expected-outcome gate joins the two layers) and 07 (synthesized Scenario
  without Qualification); no two of them run concurrently.

## 12. Conflicts with governing ADRs

Checked ADRs 0001–0007, the `CONTEXT.md` and `AGENTS.md` invariants, and the
legacy cutover boundary. The user reviewed this note on 2026-09-21 and approved
the recommended option for every item (1–6), explicitly accepting that
synthesized Scenarios are validated but not Qualified or Admitted (item 1),
that Knowledge-level compliance is unverified (item 3), and that the
`JourneyJudge` prompt is new and uncalibrated (item 6).

1. **ADR 0001** — "evolve the committed `scenario_synthesis/` prototype rather
   than build a parallel system" vs. a path that skips Blueprint → Candidate →
   Qualification → Admission. (a) *Recommended:* a separate path inside
   `scenario_synthesis/`, non-payments only, that never says Candidate,
   Qualification, Admission or library and stamps `qualification: none`.
   (b) Phase 4.5 for the new Journey: needs a deterministic mock with planted
   defects, a reviewed graph and five reviewed contracts.
2. **ADR 0005** — applicability is one "reviewed precondition matrix rather
   than … journey-specific taxonomies"; that matrix is J1-edge-bound and
   hash-pinned to `fixtures/paycard.py`. (a) *Recommended:* keep the taxonomy
   shared and closed, record this Journey's applicability in `journey.yaml`
   with all nine values accounted for. (b) Extend the reviewed contract: an
   AGENTS.md-prohibited edit without approval, validated against the J1 graph.
3. **ADR 0006** — "Simulator compliance checks this evidence on every fitness
   repetition." Nothing here does, so Knowledge level is a specification, not
   verified behavior. (a) *Recommended:* record `knowledge_evidence` and say
   compliance is unverified in the report. (b) Port `simulator_compliance.py`,
   which is bound to Qualification and payments criterion snapshots.
4. **ADRs 0002, 0004, 0007** — not engaged: no coverage, eligibility, Fitness
   or Admission claim, one Episode per Scenario. ADR 0007's "code owns
   structure, an LLM realizes narrative" and **ADR 0003**'s single archetype
   per Scenario are followed.
5. **`CONTEXT.md` vocabulary** — *Agent adapter* is "one-method", *Trace* is
   "attached to turns", *Termination* includes the Judge. Session 05 amends
   the three entries in the commit that adds the lifecycle.
6. **`CONTEXT.md` invariant 3** — "No inline judge prompts in harness code."
   `JourneyJudge` overrides the system prompt because the existing one says
   "credit-card payment assistant" and rules per Turn. It is a `GeneralJudge`
   subclass in a judge module with `Criterion` objects, which I read as inside
   the invariant; parameterizing the calibration-locked `agentsim/judge.py`
   instead buys nothing.
