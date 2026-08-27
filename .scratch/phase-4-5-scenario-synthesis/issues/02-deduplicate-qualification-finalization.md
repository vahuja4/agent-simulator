# Consolidate qualification finalization and recovery

Type: task
Status: resolved

Slice 3 originally duplicated qualification finalization and recovery logic,
risking different evidence rules for normal and resumed completion.

## Acceptance criteria

- Normal and resumed qualification use one finalization path.
- Recovery preserves fail-closed evidence validation and idempotency.
- Tests cover equivalent outcomes for uninterrupted and resumed qualification.

## Answer

Resolved by `ab4e3ce`: normal completion enters the same resume/finalization
path as interrupted completion, with recursive evidence validation before any
terminal transition. Recovery and idempotency tests cover admission and
rejection transitions.

## Comments

- Carried over from the Slice 3 merge-readiness review during main cleanup on 2026-08-27.
