# M-009: Mock does not answer concept-clarification questions

Status: deferred

## Observation

In defects-off repetition 1 of
`qualification-e8c7fb2310274ba0c6548f009cfab4c9ef4d0156c44e170ea6ad969b55f2ad73`,
the customer asked which payment option meant paying the whole bill. The mock
repeated the option values, asked for a date, and did not explain the concept;
the low-Knowledge Persona then self-resolved to statement balance.

Until this is addressed, low-Knowledge cells against the defects-off mock
cannot test whether an agent correctly answers a concept-clarification request.
The Qualification can still test the Persona's required material fluency gap.

## Decision

No mock fix in the N-007 demo path. Decide the desired clarification behavior
only after this Coverage cell qualifies, then add a deterministic regression
before changing the mock.

## Comments

Deferred on 2026-08-31 by explicit instruction. This ticket records the
M-series observation without changing mock behavior.
