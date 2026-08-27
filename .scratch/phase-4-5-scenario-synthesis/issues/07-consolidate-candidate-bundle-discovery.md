# Consolidate candidate bundle discovery

Type: task
Status: open

The final Slice 3 standards review found repeated candidate-bundle discovery
in `_unterminated_candidate`, `_next_ordinal`, and `_find_replacement`.

## Acceptance criteria

- Candidate production and qualification use one validated bundle iterator or index.
- Corrupt production records fail or quarantine consistently across callers.
- Existing ordinal, idempotency, replacement, and exhaustion behavior remains unchanged.

## Comments

- Recorded during the final merge-readiness review on 2026-08-27; deferred because the shared abstraction crosses candidate and qualification lifecycle responsibilities and is not a small merge-blocker fix.
