# Scenario synthesis Phase 4.2 notes

Date: 2026-08-18

## Recovery

The uncommitted live-batch-2 realization damage was discarded before code changes.
The restored manifest has 27 realization records: 25 marked
`unexecutable_blueprint` and two unmarked. The realization directory again has 27
YAML files. The untracked `plans/synthesis-live-batch-2-notes.md` was preserved.

## Batch semantics

Realization is now additive per deterministic sample:

- A sample candidate is reused only when it has an unmarked manifest record and its
  existing YAML loads successfully, matches the current blueprint's identity,
  behavioral class, bindings, assertions, and turn limit, and passes the prose fact
  equivalence check. Reuse makes no LLM call and does not rewrite the YAML.
- A candidate without a reusable record is attempted at most twice. A new YAML is
  created exclusively, so an unrelated or invalid existing file is failed closed
  rather than overwritten.
- Each candidate record is appended or updated in place. Records outside the current
  sample are retained unchanged, and the realization pass no longer deletes any YAML.
- New candidate records carry `attempt_count` plus `realization_outcome`:
  `first_try_success` uses one attempt, `retried_once` uses two, and
  `failed_closed` uses two after the allowed retry. A pre-existing file collision is
  failed closed with zero LLM attempts. Reused legacy records retain their original
  metadata because their historical attempt count cannot be reconstructed.
- The live entry point reports each reused candidate and ends with
  `realized / reused / retried / failed / preserved` counts. `preserved` counts
  manifest records outside the current sample.

## Verification

Offline stubbed tests cover overlap reuse without a call or rewrite, preservation of
marked records and their YAML files across a run, and manifest attempt records for
first-try success, retry success, and failed-closed outcomes. No live realization,
dry-run, or live LLM call was made in this phase.
