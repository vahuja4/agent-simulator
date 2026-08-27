# Require explicit execution mode for produce and qualify

Type: task
Status: resolved

Slice 3 originally allowed bare offline `produce` and `qualify`, conflicting
with the normative explicit-live gate.

## Acceptance criteria

- Offline development requires explicit `--stub`.
- Bare commands fail before any agent-platform client is constructed.
- `--live` remains unavailable until a live implementation exists.

## Answer

Resolved by `ab4e3ce`: `produce` and `qualify` require exactly one explicit
execution mode. `--stub` selects the offline seam, bare commands exit with
guidance, and `--live` exits as unimplemented before lifecycle or client work.

## Comments

- Carried over from the Slice 3 merge-readiness review during main cleanup on 2026-08-27.
