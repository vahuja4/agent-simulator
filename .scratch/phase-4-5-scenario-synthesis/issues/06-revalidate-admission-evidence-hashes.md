# Revalidate nested admission evidence hashes

Type: task
Status: resolved

Slice 3 originally did not revalidate nested Transcript and Trace hashes during
admission and could reuse incomplete qualification evidence.

## Acceptance criteria

- Admission recursively verifies every required Transcript, Trace, ruling, and result artifact against its recorded hash.
- Missing, incomplete, extra, or mismatched evidence fails closed and contributes no qualification evidence.
- Tests cover nested hash mismatch and incomplete-bundle reuse.

## Answer

Resolved by `ab4e3ce`: admission recursively validates exact Episode and nested
artifact inventories, schemas, identities, paths, and hashes, recomputes the
decision, and records failed validation in the rejection ledger. Tests cover
all four nested artifact classes and extra evidence.
The final merge-readiness pass additionally rederives repetition counts,
Fitness configuration, and per-Episode defect toggles from current contracts
and configuration; internally rehashed shortened or retagged evidence is
rejected and ledgered.

## Comments

- Carried over from the Slice 3 merge-readiness review during main cleanup on 2026-08-27.
