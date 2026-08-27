# Preserve the JSONL Transcript contract

Type: task
Status: resolved

Slice 3 originally wrote qualification Transcripts as Markdown, conflicting
with the repository's JSONL, append-only Transcript contract.

## Acceptance criteria

- Qualification persists schema-stable JSONL Transcripts.
- Stored Transcript metadata and hashes bind to the JSONL artifact.
- Lifecycle tests reject non-contract Transcript artifacts.

## Answer

Resolved by `ab4e3ce`: qualification writes canonical JSONL Transcripts,
hash-binds them from Episode evidence, and validates their schema before
admission. Lifecycle tests cover the contract and non-contract rejection.

## Comments

- Carried over from the Slice 3 merge-readiness review during main cleanup on 2026-08-27.
