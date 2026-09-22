# LangGraph synthesis harness — design note

Contract for sessions 02–09 on branch `codex/langgraph-synthesis-harness`.
Written 2026-09-21 (session 01), before any code existed. A session that must
deviate changes this note in the same commit and says so in its report.
Amended by session 03 (sections 4, 5, 8, 9, 11, 12), session 07 (sections
6, 7, 9, 11), session 07c (sections 6, 7, 9), session 05a (sections 1, 2,
8, 11, 12), session 05b (sections 5, 8, 9, 11), session 06c (sections 4,
5, 9, 11: Judge criteria are data in `journey.yaml`), session 08 (sections
8, 9, 11: the commands as built, the Run record, what clustering is handed)
and session 09 (sections 9, 11: the re-evaluation record; what 09 delivered).

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

- `ConversationHandle(conversation_id, fixture_state_sha256, agent)` — `agent`
  is the start response's agent kind (`stub` | `langgraph`), exposed so the
  Episode record can say which agent answered (session 05a);
  `AgentReply(user_message_id, message_id, text)` — text only, no tool calls
  cross the adapter before the conversation ends;
  `RetrievedTrace(raw: dict | None, normalized: NormalizedTrace, error: str | None)`.
- `retrieve_trace` never raises for a service-side problem; it returns the gap.
  The others raise `AdapterError(kind, detail, status, code)`,
  `kind ∈ {transport, service, protocol}`. Errors say whose fault they are:
  `transport` is a refused connection or a request timeout (infrastructure);
  `service` is one of section 3's documented errors, with the HTTP `status`
  and the service's own `code`; `protocol` is an answer outside the contract
  (malformed JSON, a missing field, a Fixture-state hash mismatch).
  `AdapterError.agent_fault` is true only for `service` + `agent_error`: the
  agent raised, which includes a model looping past its per-turn step limit.
  `to_dict()` is the form session 05b records.
- The per-request timeout is a constructor parameter,
  `JourneyServiceAdapter(base_url, request_timeout_s=120.0)` (section 8).
- **The adapter keeps its own record** (session 05a; the first draft left open
  where section 2's fallback messages come from). Per conversation it holds
  every exchange the service acknowledged — the service's message ids, role
  and text — plus the texts of sends that raised, and the `tool_failures` it
  sent. `retrieve_trace(handle)` therefore keeps its signature and the caller
  passes no Transcript in. The record is dropped at `release`, so retrieve
  comes first. A message the adapter did not observe is never invented.
- On a Fixture-state hash mismatch the adapter releases the conversation it
  refuses to use (best effort) before raising.
- Synchronous (blocking `urllib`): execution is sequential by requirement.
- `agentsim/adapters/journey_service.py` alone knows the transport, and holds
  raw → normalized (`normalize_raw_trace`). `agentsim/adapters/__init__.py` is
  not edited.

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
- **`result_available` means "the raw action carries the `result` key"**,
  nothing else. The service writes `"result": null` for a failed action; that
  is complete evidence (`result_available: true`, `result: None`, class stays
  `available`). Deriving it from `status` would be inference and would turn
  every controlled-tool-failure Episode into `error`.
- `reply_message_id: null` in the raw Trace is a recorded fact (the agent
  raised before replying), not a gap; an absent key is a gap. Such a Trace is
  `available` yet `to_trace()` refuses it — it only arises with stop reason
  `adapter_error`, which section 8 rule 1 already makes `error`.
- A header gap (`sealed` not true, no `fixture_state_sha256`, no
  `tool_failures`), an event of unknown type, or two events sharing a `seq`
  makes both classes `partial`; a repeated id makes its own class `partial`.
- Retrieval failed, or the raw payload cannot be used at all (wrong
  `trace_version`, no `events` list, another conversation's id or Fixture
  hash) → `messages` come from the adapter's own record (section 1: real
  observations carrying the service's ids), `actions = []`,
  `evidence.actions = unavailable`. Those messages have `sequence: None` —
  the service's counter lives only in the Trace — so `evidence.messages` is
  `partial` (`unavailable` when the record is empty). An unusable payload is
  still returned as `raw`. Raw messages that disagree with the adapter's
  record → `evidence.messages = partial`; the raw Trace is still what is
  normalized. A raw user message whose text matches a send that raised is not
  a disagreement (`500 agent_error` records the user message without telling
  the adapter its id).
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
`criteria: {assertions: [<id>], judge: [{id, statement, tools}]}`,
`knowledge_rules: [{id, statement}]` (the ADR 0006 referents),
`complications: {supported, unsupported: {id: reason}}`,
`max_turns_default`. Rules constrain the order of observable events only, so
alternative paths stay valid and nothing depends on the agent's workflow.

`criteria.judge` states each Judge criterion in full (session 06c): `id`,
`statement` — the wording the Judge is shown — and `tools`, the Journey tools
whose actions the criterion is about. `tools` is always written; a criterion
about the conversation rather than a tool gives `[]`. The loader refuses a
duplicate id, an empty statement, a tool outside the Journey's `tools`, an
unknown or missing field, and a `judge:<id>` rule reference to a criterion the
list does not define. `criteria.assertions` stays a list of ids into
`agentsim/journey/checks.py`. Because the wording is in `journey.yaml`, editing
it changes the `journey_sha256` every Scenario's provenance records.

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
`JourneyDefinition.judge_criteria` holds the `JudgeCriterion(id, statement,
tools)` rows, `judge_criterion_ids` is derived from them,
`judge_criterion(id)` returns one and `criteria_for_judge(ids)` returns the
`agentsim.judge.Criterion` objects the Judge is handed; both raise
`JourneyDefinitionError` for an id the definition does not define.

## 5. Criteria, Assertions and the Scenario seam

The two halves live in different places (session 06c; the user directed the
change on 2026-09-21). **Judge criteria are data in the Journey definition**:
their wording and tools are in `journey.yaml` (section 4), and the Judge and
evaluation read them from the `JourneyDefinition` they are given. Sessions
03–06 kept the wording in code as `agentsim.judge.Criterion` objects, following
the payments precedent; that was not a requirement, it meant a second Journey
needed Python for what is only wording and a lookup table, and a wording edit
did not move `journey_sha256`. **Assertions stay code**, in
`agentsim/journey/checks.py`, referenced from Journey files by stable id: they
are logic over the Normalized Trace, and stating them as data would need a rule
language — the deferred generic refactor. With the outcome ids the gate knows,
they are the remaining per-Journey Python, to be revisited when a second
Journey exists. Ids never reuse a payments id.

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
`reschedule_goal_completion`. Session 03 wrote the wording; session 06c moved
it to `journey.yaml` byte for byte, and
`tests/test_journey_definition.py` pins the SHA-256 of each statement (and
`tests/test_journey_evaluation.py` the Judge's system prompt), so a wording
change is deliberate and updates the hash in the same commit.

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
The loader validates the file alone (schema, closed sets, Assertion ids
exist). It has no Journey definition, so it cannot know which Judge criterion
ids exist and does not check them (session 06c): an id the definition does not
define is refused by `check_against_inputs` ("criteria.judge differ" — in
synthesis an `input-mismatch`, no longer `schema-invalid`) and by rule 0 of
evaluation;
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

As built (session 05b): the turn is a `JourneySimTurn(SimTurn)` carrying
`stop_reason`, and `stop` is true exactly when it is not `none`; there is no
`###STOP###` sentinel on this path. `_flip` is reused but its first line (the
payments opening) is replaced. Both payments gate texts are copied and pinned:
the system-prompt paragraph and the shorter per-turn reminder. Knowledge text
(`render_journey_knowledge`) carries every grounded fact's **value** and never
its **path**; the Fixture binding only chooses the heading a fact sits under
("the appointment you want to move", "the new time you want", "another … you
know about"), so the other-entity facts a Complication needs are kept. A
date-time is written out with its weekday, as written, never converted. The
prompt does not tell the customer today's date (it is not a grounded fact) and
forbids dates relative to today. `tool_failures` never reaches it.
`live_simulated_user(scenario, journey, model=None)` is the real wiring
(section 10); it raises a one-line `SimulatorConfigError` before any client
exists. An unusable model answer (unknown `stop_reason`, empty message without
a stop) is an `LLMError`, which the Episode records as `simulator_error`.

Session 06b: a customer whose `knowledge_evidence.kind` is
`states_rule_unprompted` is also shown the **statement** of the Journey
knowledge rule its `knowledge_evidence.rule` names, under "A rule you know
about how this works:" at the end of the knowledge text — never the rule's id.
Session 05b had found that no rule statement reached the prompt, so such a
Scenario worked only if its model-written Goal happened to spell the rule out,
and the stub's never does. `relies_on_agent_for_rule` (that customer depends on
the agent for the rule) and `material_fluency_gap` are shown no rule. A rule
statement is permitted knowledge (a represented domain rule under the
Sealed-world rule), not an evaluation criterion; nothing else the Simulated
user is shown changed, and both gate texts are still pinned byte-equal. The
statement comes from the Journey definition, so construction takes it:
`JourneySimulatedUser.for_scenario(llm, scenario, journey, *, model=None)`
(`journey` replaces `agent_role=`, which is now read from it) and
`render_journey_knowledge(scenario, journey)`; `live_simulated_user(scenario,
journey, model=None)` is unchanged. A `knowledge_evidence.rule` the definition
does not define raises `JourneyDefinitionError` from
`JourneyDefinition.knowledge_rule` while the Simulated user is being built,
for either rule-bearing kind — never a customer quietly built without the rule.

**Judge.** `JourneyJudge(GeneralJudge)` in `agentsim/journey/judge.py`
overrides only `_system_prompt` and `_render` (completed-conversation framing;
`agent_role`, Goal, required rules, criteria, transcript, projected Trace) and
inherits the schema, the single batched call and `_fail_closed`.

As built (session 06): `JourneyJudge(llm, journey)` is what evaluation is
handed; `judge_episode(scenario, trace)` binds a copy to the Episode's Scenario
and makes the one inherited `judge` call. The prompt holds the Goal, the
criteria the Scenario references, the Journey's required rules that one of
those references checks (`required_rules_for`), the transcript and the
projected Trace — never the expected outcome, `tool_failures`, the Persona or
the rule → check wiring. It tells the Judge the conversation is over and never
to answer `continue`. `JUDGE_MODEL = "gpt-5.5"` is a literal, so
`AGENTSIM_MODEL` cannot move it; `live_journey_judge(journey, *,
simulator_model=None, enforce_model_family_separation=False)` is the real
wiring and raises a one-line `JudgeConfigError` before any client exists.
Each Judge criterion's `tools` in `journey.yaml` names the tools it is about
(as `AssertionSpec.tools` does), because the Judge rules once and names no
Turn: evaluation points a Judge failure at those tools' actions and the
messages around them. Session 06 kept that table in `checks.py`; session 06c
moved it into the Journey definition, and `judge.py` no longer imports
`checks`.

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
is rejected with reason `model-supplied-derived-field` — never overridden, even
when the value agrees with what code derives.

`knowledge_evidence.kind` is a closed set, one kind per Knowledge level because
identical behavior cannot evidence two levels (ADR 0006); the names are the
Phase 4.5 ones. The loader enforces kind ↔ level, the field each kind carries,
and that a `referent` is the `path` of one of the Scenario's own
`grounded_facts` (a wrong label needs a real fact); `check_against_inputs`
already checks that a `rule` is a `journey.yaml` `knowledge_rules` id.

| `knowledge_level` | `kind` | carries |
|---|---|---|
| `low` | `material_fluency_gap` | `referent` |
| `medium` | `relies_on_agent_for_rule` | `rule` |
| `high` | `states_rule_unprompted` | `rule` |

`scenario_id`'s 12 hex digits are the SHA-256 of the canonical JSON of
`{set_id, spec, narrative}`. `journey_sha256` hashes the bytes of
`journey.yaml`; `fixture_state_sha256` is `FixtureState.sha256` — the
canonical-JSON hash the agent service returns and the Normalized Trace records,
so a Scenario, its Episode and its Fixture state can be matched by one value.
`provenance.json` records the Fixture file's byte hash as well.

```
synthesized_journey_scenarios/<journey_id>/<set_id>/
  provenance.json                    # input hashes, config, model, timestamp, counts
  accepted/<scenario_id>.yaml
  rejected/<spec_id>-<attempt>.json  # spec, raw model output, reason codes
```

Reason codes: `provider-error`, `malformed-output`,
`model-supplied-derived-field`, `schema-invalid` (the loader),
`input-mismatch` (`check_against_inputs`), `sealed-world-violation`. An
existing set directory is never overwritten, and an output root under
`scenarios/`, `synthesized_scenarios/` or `generated_scenarios/` is refused.
`verify_provenance(set_dir, journey_dir)` re-checks the three hashes and every
accepted file.

`provenance.json` carries `status`. A run that reaches its end writes
`"complete"`. A run that fails unexpectedly after its set directory exists — a
provider raising something other than `LLMError`, a failed write, an interrupt —
keeps what it wrote and still writes `provenance.json`, with
`"status": "aborted"` and `"error": {type, message, spec_id}`; `counts`, `specs`
and `accepted` describe what exists. Partial evidence is preserved rather than
cleaned up (a live run has paid for it), and the set id stays taken.
`synthesize_set` raises `SynthesisAborted` from the original error — not a
`ValueError`, so it is never read as a configuration error — and lets an
interrupt propagate as itself. `verify_provenance` reports an aborted set as a
problem. A set directory that appears between the existence check and `mkdir`
is a `SynthesisConfigError`: nothing of this run was written.

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
seed (appointment × bookable slot × archetype × Knowledge level × supported
Complication × tool-failure condition); derives `expected_outcome` and
`criteria` from `journey.yaml`; asks the model for three narrative fields;
validates; saves. Two attempts per spec, every failed one saved; the second
attempt is shown the first one's reason. A shortfall is printed and exits
non-zero. No coverage claim is made.

Round-robin means each axis takes its least-used value first, ties broken by
one seeded shuffle of the combinations — plain lock-step indexing would pair
same-length axes (appointment *j* always with archetype *j*). Tool-failure
conditions are the `when` conditions of `journey.yaml`'s valid outcomes, so
every planned condition has a derivable expected outcome. Variation settings
(`VariationSettings`) narrow the axes; a value outside a closed set, a
Complication the Journey lists as unsupported, or a condition with no valid
outcome is refused before anything is generated. So are a duplicate value
(tool-failure conditions compare as sets, so two orderings of one condition
are a duplicate), an explicitly empty axis — omitting an axis means every
supported value, `()` never does — and a supported Complication for which the
generator has no writing direction (goal shift and multi-intent turn today).

Code also owns what a Complication needs from Fixture state (ADR 0005), and a
combination that lacks it is not planned: mid-conversation correction names a
second bookable slot to ask for first; false premise names the appointment's
provider and another real provider as the believed value — an incorrect belief
about real Fixture state, never an invented fact; ambiguous reference needs
another scheduled appointment of the same customer and service. The extra
facts join `grounded_facts`. The model is shown the spec without
`tool_failures`, and never the expected outcome or the checks: a customer
knows none of them.

Validation: schema; closed sets; every fixture id resolves and belongs to the
Scenario's customer; target slots are available and match the appointment's
service; each grounded fact equals Fixture state; criterion references exist;
the narrative holds no identifier, code, date or time that is not a grounded
fact (Sealed-world rule). All but the last run through the section 5 seam
(`load_journey_scenario` on the exact text to be saved, then
`check_against_inputs`). The narrative check is lexical: every digit-bearing
token and every month or weekday name must come from a grounded fact, with
dates and times accepted in their usual written forms, including a grounded
date-time quoted verbatim (UTC offset and all) and its `HH:MM:SS`. It checks tokens one at
a time, so it can reject honest text (a count written as a digit) and cannot
prove a sentence true. Passing validation is not evidence of test quality,
coverage, Qualification or Admission; the module docstring, `provenance.json`
and the command output all say so.

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

`async run_episode(scenario, *, fixture_state, adapter, simulated_user,
episode_dir, service_url, time_limit_s=600.0, clock=time.monotonic) ->
EpisodeRecord` (session 05b). The Simulated user is passed in ready-made, so
the loop needs no Journey definition and no model. Each user message is
appended to the Transcript **before** `send_message` — a send that fails is
not in the adapter's record, so the Transcript is where it survives — and each
reply as it arrives. A final message sent with a stop is delivered and its
reply saved; an empty one stops silently. A Turn counts once its reply
arrived. The Turn limit is checked before the time limit, both between Turns.
Retrieve comes before release on every path because release drops the
adapter's record; release is attempted even when retrieval or saving failed,
and a release failure is recorded without changing the stop reason. If
`start_conversation` fails there is no handle, so neither is attempted and
`normalized_trace.json` is written with both evidence classes `unavailable`
and reason `no conversation was started`. Any exception from the Simulated
user is `simulator_error`; an `AdapterError` is `adapter_error`; anything else
(a harness bug, an interrupt) still gets retrieve, release and an
`episode.json` with `status: aborted`, then propagates, so `BatchRunner`
records the Run as `error`. An Episode directory that already holds a
Transcript or an `episode.json` is refused before any write.

Stop reasons: `user_finished`, `user_gave_up`, `turn_limit`, `time_limit`,
`adapter_error`, `simulator_error`. The HTTP request timeout is an adapter
parameter defaulting to 120 s, not the first draft's fixed 60 s: one LangGraph
turn makes several model calls at up to 30 s each with one retry (session
05a). The Episode time limit, checked between Turns, becomes a parameter
defaulting to 600 s in session 05b (first draft: a fixed 300 s).

Outcome — first matching rule (`agentsim/journey/evaluation.py`):

0. `episode.json` or `scenario.yaml` cannot be read → `error` (added in
   session 06; `evaluation.json` is still written).
1. Stop reason `adapter_error` or `simulator_error`, `status: aborted` (its
   stop reason is null), or an unknown stop reason → `error`. `episode.json`'s
   `error` is copied into `evaluation.json` as `episode_error`, unchanged.
2. An evidence class not `available`, `normalized_trace.json` unreadable, an
   Assertion or the outcome gate `unavailable`, or a Trace `to_trace()`
   refuses → `error`. Assertions are not run on incomplete evidence.
3. Any Assertion `failed` → `fail`; the Judge is not called, so cannot override.
4. Judge raises (`LLMError` or anything else) → `error`.
5. Judge decision `fail` (after `_fail_closed`), or a referenced criterion the
   verdict does not affirm → `fail`. A `fail` with every criterion affirmed
   carries one failure with id `judge_decision`.
6. Judge `pass` **and** `expected_outcome_evidenced` → `pass`.
7. Otherwise → `task_incomplete`; `evaluation.json` `incomplete` says why,
   since the gate carries no `FailureRecord`. A Judge `continue` lands here
   even when the outcome is evidenced: it is never a `pass`.

The Trace is projected only after rules 1 and 2. So an Episode whose conduct
is clean but whose outcome is not evidenced is `task_incomplete`, whatever the
stop reason.

`run_episode` and `evaluate_episode` are `async def`: the Simulated user and
the Judge are async. They run on `BatchRunner`'s loop, and the CLI enters
through the single process-local event loop (`scenario_synthesis/_async.py`).
The adapter stays blocking; with `concurrency=1` that is acceptable.

Each `FailureRecord` carries the check id, an explanation, and
`data = {stable details…, "evidence": {"message_ids", "action_ids", "files"}}`;
clustering similarity runs over `data`, so free text stays in `message`.
`files` are names relative to the Episode directory, identical for every
Episode, so they do not pull clusters apart. A Judge failure's stable details
are `stop_reason`, `expected_outcome`, `outcome_status` and `tools`; its
`turn_index` is `None`. `message_ids` and `action_ids` differ whenever two
conversations differ in length, so clustering is never shown them (session
08): `run` writes each failure into `manifest.json` — the only thing
`cluster_failures` reads — through `agentsim.journey.report.clustering_view`,
which drops those two lists and nothing else. `evaluation.json` keeps the full
record, and the report links to it.
One Episode per Scenario (`seed=0`); no Pass rate over Seeds is reported.

## 9. Run directory and commands

The Run directory is a `BatchRunner` batch directory; the Episode directory is
its `runs/<run_key>/`:

```
journey_runs/<run_id>/
  journey_run.json          # the Run record: status, inputs, agent kind, models, error
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

`transcript.jsonl` lines (session 05b): user `{turn, role: "user", text,
intent, stop_reason, at}` — no `message_id`, the service assigns it only on
acknowledgement; agent `{turn, role: "agent", text, message_id,
user_message_id, at}`. `episode.json`: `schema_version`, `status`
(`complete` | `aborted`), `scenario_id`, `journey`, `service_url`, `agent`,
`conversation_id`, `fixture_state_sha256`, `simulator_model`, `stop_reason`,
`turns_completed`, `max_turns`, `time_limit_s`, `started_at`, `ended_at`,
`duration_s`, `error`, `retrieval {attempted, raw_trace_saved, error,
evidence}`, `release {attempted, error}`. `error` is `null` or one of
`{source: "adapter", operation, turn?, adapter_error: AdapterError.to_dict()}`,
`{source: "simulated_user", turn, type, message}`,
`{source: "harness", type, message}`. It holds no outcome and no Verdict.
`scenario.yaml` is the Scenario as it ran, written from the loaded object and
readable by `load_journey_scenario`. `raw_trace.json` exists whenever a
payload arrived, an unusable one included.

`async evaluate_episode(episode_dir, judge, journey, *, criteria=criteria_for)
-> EvaluationResult` with `.to_run_result()` (an empty `Trace` when evidence is
unavailable; `llm_calls` counts the Judge call only). It reads the Scenario
from `<episode_dir>/scenario.yaml`. `journey` is the `JourneyDefinition` the
Scenario was written for (session 06c): the Judge protocol exposes only
`judge_episode`, so the definition is an explicit argument and the Judge
doubles stay small. `criteria(scenario, journey)` resolves a Scenario's
criterion references to an `EvaluationCriteria` (Assertions, outcome gate,
Judge criterion → tools): the mechanics take criteria as input and hold none.
Two refusals are rule 0 (`error`), never a crash and never a default of "no
tools": the Scenario's `journey` is not the definition's `journey_id`, and a
Scenario Judge criterion the definition (or the handed criteria) does not
define.
`evaluation.json`: `schema_version`, `scenario_id`, `journey`,
`conversation_id`, `episode_status`, `stop_reason`, `expected_outcome`,
`outcome`, `rule {number, name}`, `explanation`, `evidence`, `assertions`
(`AssertionResult.to_dict()`), `outcome_evidence`, `judge {called, model,
verdict, error}`, `failures` (`FailureRecord.to_dict()`), `incomplete`,
`episode_error`, `simulator_model`. It is derived, so re-evaluating replaces
it. `run`
passes `BatchRunner(concurrency=1)` an async `execute` = `await run_episode` +
`await evaluate_episode` (section 8), **one Scenario per `BatchRunner.run`
call, in a plain loop** (session 08). Handing it every spec at once would
leave sequencing to a semaphore inside `asyncio.gather`, and `gather` does not
stop the siblings when one task is interrupted; a loop makes "sequential" and
"an interrupt stops the Run" true by construction. `BatchRunner` never retries
(`retry_errors=False`): `run_episode` refuses a directory that already holds
an Episode. An `execute` that raises is that Scenario's `error` and the loop
goes on. `summarize` calls `cluster_failures` unchanged (it clusters `fail`
only, so `error` never enters an agent-failure cluster), skips
`label_clusters`, and renders `agentsim/journey/report.py`.

**The Run record** `journey_run.json` (session 08) is written before the first
Episode with `status: running` and finished as `complete` or `aborted`:
`schema_version`, `run_id`, `status`, `journey_id`, `journey_dir`,
`journey_sha256`, `fixture_state_sha256`, `scenario_set`, `scenario_ids` (the
plan, so Scenarios the Run never reached can be named), `service_url`, `agent`,
`simulator_model`, `judge_model`, `enforce_model_family_separation`,
`request_timeout_s`, `episode_timeout_s`, `started_at`, `ended_at`,
`re_evaluation`, `error {type, message}`. `BatchRunner`'s manifest says
`pending | running | completed` per Episode but nothing about the Run, so the
AGENTS.md rule (a command that writes before fallible work leaves a record
marked aborted) needs this file. Whatever escapes `BatchRunner` — an interrupt,
a failed write — marks the Run `aborted` with the error, keeps every completed
Episode (the interrupted one has its own `episode.json` with `status:
aborted`), prints one `ABORTED:` line and exits 1; an interrupt then propagates
as itself. A Run directory is never reused: `run` refuses an existing one.
Anything other than `complete` is reported as aborted, so a killed process that
never wrote its end is not mistaken for a finished Run.

**The report** (`agentsim/journey/report.py`, from the Run directory alone).
Near the top, once: nothing checks Simulated-user fidelity, a failure may be
the Simulated user's doing, read the conversation before treating a cluster as
an agent defect, and a reported Run needs Spot-check records — wording only,
no detection (section 12 item 3). Then the outcome counts and one section per
outcome, so an Episode that is counted is always listed: failure clusters
(`fail`; presented as similar failure symptoms, never as proven common root
causes; one row per failure, so an Episode with two failures has two rows);
`task_incomplete`, which has no failure record and can never be in a cluster,
grouped by the structured reason `evaluation.json` `incomplete` holds (expected
outcome, outcome status, stop reason, Judge decision); agent errors (`service`
+ `agent_error`: the agent crashed or looped) apart from infrastructure and
harness errors, each grouped by the adapter error kind and service code in
`episode.json`, or by the evaluation rule that made it an error; and, for an
aborted Run, what was interrupted or never started. Every row links the
conversation, raw Trace, normalized Trace, evaluation result and Episode
record that exist, relative to the Run directory. The Judge call count is
labelled as not a total: the Simulated user's calls are not recorded.

`journey_runs/` is git-ignored (session 08): a development Run is not
evidence, and a reported Run is outside these sessions. `journey_spot_checks/`
is **not** ignored — those records are the evidence. Known consequence: a
Spot-check record validates only on a machine that still has the Run it
points to.

**Spot-check records** (session 06b) are the one thing about a Run kept
outside its directory, because they are a human's and must outlive a
re-evaluation: YAML files under `journey_spot_checks/`, one record per
reviewed Episode — `run_id`, `scenario_id`, `reviewer`, `date`, and for each of
`persona`, `knowledge_level`, `complication`, `grounded_facts` a
`{verdict: faithful | drifted | not_applicable, note}`. The format is
documented in `agentsim/journey/spot_check.py`;
`load_spot_check_records(path, *, runs_root="journey_runs")` refuses unknown
fields, unknown verdicts, a `drifted` verdict with no note, a duplicate record,
and a record whose Episode (`<runs_root>/<run_id>/runs/*/episode.json` with
that `scenario_id`, exactly one) does not exist.
`.venv/bin/python -m agentsim.journey.spot_check <file> [--runs-root …]`
validates a file (exit 0, or 2 with one line) and does nothing else. See
section 12 item 3 for why this is a human record and not a check.

Entry point `scripts/journey_harness.py` (scripts are this repository's
composition roots; `run_calibration.py` already imports both packages):

```
.venv/bin/python scripts/journey_harness.py synthesize --journey journeys/appointment_rescheduling \
    --count 6 --set-id <set_id> [--seed 0] [--stub] [--output-root synthesized_journey_scenarios]
.venv/bin/python scripts/journey_harness.py run --journey journeys/appointment_rescheduling \
    --scenarios <set dir> --service-url http://127.0.0.1:8765 --run-id <run_id> \
    [--output-root journey_runs] [--simulator-model …] [--request-timeout 120] \
    [--episode-timeout 600] [--enforce-model-family-separation]
.venv/bin/python scripts/journey_harness.py run --journey journeys/appointment_rescheduling \
    --re-evaluate journey_runs/<run_id>
.venv/bin/python scripts/journey_harness.py summarize journey_runs/<run_id>
```

`run` takes a required `--journey <dir>` (session 08; carried over from session
03): `check_against_inputs` needs the Journey definition and Fixture state, and
`--scenarios` alone does not locate them — explicit beats inferring a path
from `provenance.json`. Before anything is written `run` refuses, with exit
status 2 and one line: a set that fails `verify_provenance` (an aborted,
half-written set included), a Scenario whose `synthesis.journey_sha256` or
`fixture_state_sha256` does not match that directory, a Scenario
`check_against_inputs` refuses, an existing Run directory, missing model
configuration, and a service that does not answer. It learns which agent
answers from a probe conversation (start, then release — the contract has no
other way to ask) and prints `agent: stub|langgraph` before the first Episode.
The Journey definition is loaded once and that one object is handed to
`live_journey_judge` and to every `evaluate_episode` call. Exit status: 0 when
the Run finished, whatever the outcomes — a `fail` or an `error` Episode is a
result, not a command failure; 1 aborted after the first write; 2 unusable
request.

`run --re-evaluate <run dir>` evaluates the saved Episodes of an existing Run
again and replays nothing: `evaluation.json` is derived and replaced, the
manifest records are rewritten through `BatchRunner`, conversation files are
untouched. It makes the same hash check as `run` and refuses, before any
write, a Journey directory edited since the Scenarios were written — criterion
wording lives in `journey.yaml`, so the Episodes would otherwise be judged with
other wording. An aborted Run stays aborted; Scenarios it never started are
left as they are. Whether the conversations finished and whether the last
re-evaluation finished are two facts, recorded apart (session 09): the Run's
`status`, `ended_at` and `error` are never touched by a re-evaluation, which
writes its own `re_evaluation {status: running | complete | aborted,
started_at, ended_at, error}` entry in `journey_run.json`. Session 08's first
draft reused `status`, so an interrupted re-evaluation left a finished Run
`aborted` for good. The report and `summarize` name an aborted re-evaluation
as such: the Episodes it did not reach are counted as not finished and keep
their earlier `evaluation.json`.

`synthesize` is `journey_synthesis.synthesize_command(...)`, which prints the
report and returns the exit status: 0; 1 on a shortfall, or when the run
aborted after writing files (one `ABORTED:` line naming the error and the set
directory, section 6); 2 for an unusable request or missing configuration,
always before any network call or write. Session 08 only parses arguments for
it.
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
| 05a | HARNESS | `agentsim/adapters/{conversation,journey_service}.py`; `tests/test_journey_adapter.py`; `tests/fixtures/journey_agent_raw_traces/` (raw Traces captured from AGENT's stub service, pinned for contract tests); `CONTEXT.md` (Agent adapter, Trace) |
| 05b | HARNESS | `agentsim/journey/{simulated_user,episode}.py`; `tests/test_journey_{simulated_user,episode}.py`; `CONTEXT.md` (Termination, Transcript); the `agentsim/journey/__init__.py` docstring (running a Scenario, unlike loading one, does import the payments simulator) |
| 06 | HARNESS | `agentsim/journey/{judge,evaluation}.py`; `JUDGE_CRITERION_TOOLS` in `agentsim/journey/checks.py` (no wording touched); `tests/test_journey_evaluation.py`; `CONTEXT.md` (Verdict) |
| 06b | HARNESS | `agentsim/journey/simulated_user.py` (the rule statement in the knowledge text; construction takes the Journey definition), `JourneyDefinition.knowledge_rule` in `agentsim/journey/definition.py`, `agentsim/journey/spot_check.py`; `tests/test_journey_{simulated_user,spot_check}.py`; `CONTEXT.md` (Spot-check record); sections 5, 9 and 12 of this note |
| 06c | HARNESS | `journeys/appointment_rescheduling/journey.yaml` (`criteria.judge` in full); `agentsim/journey/{definition,checks,judge,evaluation,scenario}.py`; their tests and `tests/journey_trace_builder.py`; sections 4, 5 and 9 of this note |
| 07 | HARNESS | `scenario_synthesis/journey_synthesis.py`; `tests/test_journey_synthesis.py`; `CONTEXT.md`; the `knowledge_evidence.kind` closed set in `agentsim/journey/scenario.py` with its tests and `tests/journey_trace_builder.py` |
| 08 | HARNESS | `scripts/journey_harness.py`; `agentsim/journey/report.py`; `tests/test_journey_{cli,report,e2e}.py`; `tests/journey_run_doubles.py` (a whole Run on doubles, reusable by 09); `.gitignore` (`journey_runs/`); `CONTEXT.md` (Run); sections 8, 9 and 11 of this note |
| 09 | both | `docs/journey-harness-setup-and-run.md`; AGENT `README.md` (running the harness, the contract re-check); `scripts/recapture_journey_agent_traces.py` (re-captures the pinned raw Traces from AGENT's stub and compares); `synthesized_journey_scenarios/appointment-rescheduling/stub-walkthrough/` with its `README.md` (stub-generated walkthrough set); the re-evaluation record (section 9) in `scripts/journey_harness.py` and `agentsim/journey/report.py`; the guarded no-conversation Trace save in `agentsim/journey/episode.py`; `docs/solutions/journey-{re-evaluation-has-its-own-record,harness-review-findings-sessions-02-09}.md`; final report |

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
  Normalized Trace), 05a (Agent adapter, Trace), 05b (Termination), 06 (Verdict: the
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

   **Automated checks of the Simulated user were considered on 2026-09-21 and
   rejected by the user — do not re-propose them.** What was considered:
   lexical matching of the customer's messages against the Scenario (did it
   state the rule, use the wrong label, withhold the fact), a self-report field
   in the Simulated user's structured answer, per-Episode deviation flags, and
   a fidelity Judge. Why not: the customer is an LLM writing free text, so a
   text match misses every honest paraphrase and fires on coincidences; a
   self-report is the same model grading itself; and a fidelity Judge has no
   labelled data to be tuned against, so its rulings would be one more
   unvalidated opinion. Each would raise false alarms that cost more attention
   than they save, and a quiet check would be read as evidence it is not.
   Deterministic checks stay where the evidence is structured (Assertions over
   the Normalized Trace, provenance hashes). Simulated-user fidelity on this
   path is therefore a **human** judgement: the Persona-fidelity spot-check
   AGENTS.md requires, recorded as Spot-check records (section 9). Those
   records are the only fidelity evidence this path has, and they are the
   labelled data a fidelity Judge could later be tuned against — the point at
   which this decision may be revisited, not before. Session 06b closed the
   one concrete gap behind the question (a high Knowledge level customer was
   never shown the rule it is to state; section 5) and added no check.
4. **ADRs 0002, 0004, 0007** — not engaged: no coverage, eligibility, Fitness
   or Admission claim, one Episode per Scenario. ADR 0007's "code owns
   structure, an LLM realizes narrative" and **ADR 0003**'s single archetype
   per Scenario are followed.
5. **`CONTEXT.md` vocabulary** — *Agent adapter* is "one-method", *Trace* is
   "attached to turns", *Termination* includes the Judge. Session 05a amends
   *Agent adapter* and *Trace* in the commit that adds the lifecycle; session
   05b amends *Termination* with the loop.
6. **`CONTEXT.md` invariant 3** — "No inline judge prompts in harness code."
   `JourneyJudge` overrides the system prompt because the existing one says
   "credit-card payment assistant" and rules per Turn. It is a `GeneralJudge`
   subclass in a judge module with `Criterion` objects, which I read as inside
   the invariant; parameterizing the calibration-locked `agentsim/judge.py`
   instead buys nothing.
