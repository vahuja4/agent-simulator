# Phase 1 Build Plan

Scope: design doc §8 Phase 1 only, with the six amendments applied. Done = one mock J1
one-time-payment conversation runs end to end offline (mock + orchestrator) plus a
stubbed-LLM e2e test producing a pass/fail verdict, with tests per component.

## File tree

```
agentsim/
  __init__.py            keep
  clock.py               NEW  frozen injectable Clock (amendment 6); no datetime.now() anywhere else
  types.py               CHANGE  Message/ToolCall/AgentInput/AgentResponse only;
                         ToolCall gains `result` payload; verdict types stay;
                         TurnRecord/RunResult/Failure move into trace.py (deleted here)
  trace.py               NEW  canonical versioned Trace schema (amendment 2):
                         explicit `schema_version` field serialized with every
                         trace; full JSON round-trip (to_dict/from_dict,
                         to_json/from_json) from day one — Phase 4 reporting and
                         failure reproduction read serialized traces.
                         Trace{schema_version, conversation_id, turns, outcome},
                         TraceTurn{speaker, text, intent (user), tool calls
                         w/ name+args+result (agent), selected_card state};
                         user turn between validate and submit recorded distinctly
                         (amendment 4); docstring notes which future checks need
                         results vs calls-only.
                         MUST NOT import verdict types or judge.py — the trace is
                         the immutable record of what happened; verdicts are
                         derived from it and live in types.py / orchestrator
  registry.py            NEW  §2 tool-name constants (J1 + shared): PayeeList,
                         FundingAccountPicker, AddOptionsOneTimePayment,
                         AddValidateOneTimePayment, AddOneTimePayment,
                         KnowledgeBaseSearch — the one mapping module
  llm.py                 keep impl; wrap behind small LLMClient protocol/class
                         (`async structured(...)`) so simulator & judge take an
                         injected client and tests stub it
  adapters/
    __init__.py          FIX  export AgentAdapter + MockPayCardAgent (rename from
                         MockPaymentsAgent); drop http_adapter import until Phase 5
    base.py              keep as-is
    mock_paycard.py      NEW  MockPayCardAgent: deterministic rule-based state
                         machine over fixtures, no LLM (amendment 1). Per-conversation
                         state modeled on Sierra store: selected card, funding
                         account, fetched options, PendingPayment staging;
                         AddValidateOneTimePayment stages the pending object,
                         AddOneTimePayment consumes it only after explicit user
                         confirmation. MockConfig dataclass with per-defect bool
                         flags D1–D7, all False, unused for now
  simulator.py           NEW  UserSimulator (amendment 5): role-reversed prompt,
                         persona + goal + grounded card/account fixtures, per-turn
                         intent step + short reply in one structured LLM call,
                         ###STOP### sentinel; max_turns handled by orchestrator as
                         `task_incomplete` outcome (not a policy failure)
  judge.py               NEW  GeneralJudge (amendment 3): sees transcript + trace
                         (tool calls with results), one structured LLM call per
                         turn, all criteria batched, forced verdict
                         continue/pass/fail, fail-closed (non-explicit-pass = fail).
                         Explicit-confirmation is a judge criterion (amendment 4)
  orchestrator.py        NEW  turn loop: simulator → adapter → append to Trace →
                         judge; stops on pass/fail/###STOP###/max_turns; returns
                         Trace with outcome ∈ {pass, fail, task_incomplete, error}

fixtures/
  __init__.py            NEW
  paycard.py             NEW  plain-Python fixture data: cards (incl. two Freedom
                         cards for later), funding accounts, balances, amount
                         options, due dates; FROZEN_NOW constant for the Clock

tests/
  conftest.py            NEW  frozen clock fixture, StubLLMClient (scripted
                         structured responses)
  test_trace.py          NEW  schema round-trip, version tag, results-required note
  test_mock_paycard.py   NEW  direct unit tests of the J1 flow, no LLM: happy path
                         tool sequence, validate-stages-pending, submit-refuses-
                         without-pending/confirmation, card-switch resets options
  test_orchestrator.py   NEW  scripted fake simulator + mock agent → trace shape,
                         max_turns → task_incomplete
  test_simulator.py      NEW  stubbed LLM: prompt grounding, intent step, STOP parse
  test_judge.py          NEW  stubbed LLM: fail-closed on malformed/missing pass,
                         verdict mapping
  test_e2e.py            NEW  full loop with stubbed simulator+judge LLM against the
                         real mock: one-time payment runs end to end → pass verdict;
                         a judge-fail path → fail outcome. Asserts on TRACE CONTENTS,
                         not just the verdict: exact J1 tool-call sequence with
                         result payloads, PendingPayment staged by validate then
                         consumed by submit (matching formId), a user turn between
                         validate and submit, and JSON round-trip of the trace —
                         that is the contract everything later builds on

pyproject.toml           CHANGE  requires-python >=3.12; dev deps + pytest-asyncio
```

## Build order (tests alongside each step)

1. `clock.py` + `fixtures/paycard.py`
2. `trace.py` (canonical schema first) + `test_trace.py`
3. `types.py` changes (ToolCall.result; trim moved types)
4. `mock_paycard.py` + `registry.py` + `test_mock_paycard.py` — fully offline
5. `orchestrator.py` + `test_orchestrator.py`
6. `simulator.py` + `test_simulator.py` (LLMClient wrapper in llm.py here)
7. `judge.py` + `test_judge.py`
8. `test_e2e.py`

## Notably out of scope

Journeys J2–J5, planted-defect behavior (flags exist but do nothing), assertion engine,
scenario YAML, clustering/reporting, HTTPAgentAdapter, CLI (`python -m agentsim`).
