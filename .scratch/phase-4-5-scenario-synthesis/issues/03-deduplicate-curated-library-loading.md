# Consolidate curated Scenario library loading

Type: task
Status: resolved

Slice 3 originally duplicated curated Scenario library loading, creating
multiple interpretations of the admission source.

## Acceptance criteria

- All lifecycle operations load the curated Scenario library through one implementation.
- Duplicate and invalid Scenario handling is consistent across callers.
- Existing lifecycle tests cover the shared loader boundary.

## Answer

Resolved after rebase: `load_curated_library` delegates to the canonical
`load_library` implementation, while strict origin checks remain shared at the
Scenario-loader boundary. Lifecycle tests cover cross-loader rejection.

## Comments

- Carried over from the Slice 3 merge-readiness review during main cleanup on 2026-08-27.
