# Make Detection-unproven independent of Admission status

Status: deferred

## Problem

Detection-unproven describes the Coverage cell's evidence class: no applicable
Fitness target means sensitivity remains unproven. It must therefore be true
for both admitted and rejected Candidates from that cell. `evaluate_admission`
currently returns `detection_unproven=False` through `_reject`, so the rejected
ordinal-0 decision records the wrong provenance.

## Acceptance criteria

- A Candidate whose Blueprint has no applicable Fitness target records
  `detection_unproven=true` regardless of Admission status.
- A focused regression covers a rejected defects-off Qualification.
- Existing Admission, Fitness, and fail-closed behavior remains unchanged.

## Comments

Deferred on 2026-08-31 by explicit instruction during the N-007 demo path.
The expected implementation is a narrow decision-construction fix plus one
test; do not rewrite the historical rejection decision.
