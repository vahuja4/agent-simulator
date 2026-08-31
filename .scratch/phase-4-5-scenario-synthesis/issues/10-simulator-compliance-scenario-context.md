# M-012: Supply Scenario contract evidence to simulator compliance

Status: deferred

## Observation

`simulator_factual_grounding` requires checking customer claims against the
Scenario Goal and supplied knowledge, but `GeneralJudge.judge` receives only
the Transcript and tool trace. During the N-007 curated calibration, this
caused false failures for the goal-grounded $875.20 payment in
`j5-cancel-autopay-pending` until the calibration Judge received the Scenario
contract as separate evidence.

## Decision

Do not alter the Qualification harness in the N-007 demo path. Design a narrow
context-delivery seam that preserves the approved criterion wording and the
shared Judge interface, then live-verify it before use.

## Acceptance criteria

- Simulator compliance can distinguish a Scenario-grounded opening claim from
  an invented fact even when the assistant never repeats or tool-verifies it.
- The Scenario contract is evidence, not appended criterion wording.
- Existing Judge criteria and mock behavior remain unchanged.

## Comments

Recorded by the required compound pass on 2026-08-31; no fix in this session.
