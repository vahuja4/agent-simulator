# Scenario synthesis Phase 4.4 notes

Date: 2026-08-18

## Dry-run selection

The dry-run entry point now resolves successful realization history for a batch to
exactly one record per unique `blueprint_id`. It scans append-only history from
newest to oldest, so a later successful record, including a zero-attempt reuse
record, takes precedence over an earlier success for the same blueprint. Failed
records remain ineligible.

This change is limited to dry-run candidate selection. Realization behavior,
manifest history, generated scenario YAML, and other live artifacts were not
changed, and no live LLM call or dry-run was made.

## Verification

The Phase 4 test covers a label containing an original success followed by a reuse
record for the same blueprint and verifies that only the later reuse record is
selected. The focused Phase 4 tests passed with 4 tests. The complete offline suite
passed with 299 tests and one live test deselected.
