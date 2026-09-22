# Codebase simplification review — 2026-09-22

Reviewed the current code at `428f0a0`, concentrating on the payments batch
utilities, Journey-definition path and scenario synthesis. This is a review,
not an implementation change or a complete correctness audit. Recommendations
are deliberately small; no new framework or dependency is needed.

## 1. One unfinished count for both report outputs

**Confirmed bug, P2.** `agentsim/journey/report.py:131` populates
`RunSummary.not_finished` with only `len(run.not_finished)`, while `_outcomes`
at line 353 also counts `run.never_started`. The CLI at
`scripts/journey_harness.py:407` therefore understates unfinished work after an
interruption before all planned Scenarios have a manifest entry.

Reproduced offline using `tests.journey_run_doubles.play_run` with
`["pass", "interrupt", "pass"]`, followed by `summarize_command`:

```text
CLI: pass 1, fail 0, task_incomplete 0, error 0, not finished 1
Markdown: | 1 | 0 | 0 | 0 | 2 |
```

Use one count on `_Run` in both outputs. Keep the two underlying lists because
the report distinguishes interrupted Episodes from never-started Scenarios.
Extend the existing interruption test in `tests/test_journey_cli.py:294` to
assert the CLI count too; it currently checks only the Markdown count. This
changes behavior and should be a bug-fix commit separate from refactoring.

## 2. Consolidate atomic file writing in the existing utility module

The temporary-file/write/replace/cleanup sequence appears in:

- `agentsim/_io.py:12` (`_atomic_json`);
- `agentsim/batch.py:40` (`_atomic_text`);
- `agentsim/acceptance.py:160` (inline JSON writing);
- `agentsim/report.py:134` (inline text writing);
- `scenario_synthesis/evidence.py:35` (`atomic_text`).

Put the shared text writer beside `_atomic_json` in `agentsim/_io.py` and
reuse it. The matching JSON writers can use the existing JSON helper.
`agentsim/journey/report.py:23` can then import the utility directly instead
of importing the batch execution module solely for its private text writer.

Preserve output bytes, trailing newlines, atomic replacement and cleanup.
Do not conflate this with canonical hashing: the serializers have different
Unicode and fallback policies. The Episode writer also has its own formatting;
sharing its text operation need not change its JSON serialization. Preserve
the Transcript's separate flush/fsync behavior. Existing batch, acceptance,
reporting and evidence tests should remain green.

## 3. Remove the obsolete prototype writer, retaining reconciliation

`scenario_synthesis/enumerate.py:125` contains `write_generation` and private
manifest/archive helpers; `_exclusion_counts` at line 425 serves that writer.
These functions plus `scenario_synthesis/sample.py` account for 266 lines,
before removing their now-unused imports, spacing and module entry point.

Repository caller searches found the writer used by legacy tests and its own
module entry point. That entry point calls the default writer, which refuses
to write Historical quarantine. Its sampling functions are not called by the
current planner's reconciliation path.

The production dependency remains:

```text
planner -> compatibility -> _enumerate_blueprints / BlueprintValidator
```

Remove just the writer, writer-only helpers, module entry point and sampling
module, with obsolete tests retired alongside them. Retain enumeration and
validation used by reconciliation. Do not delete the whole legacy subsystem
or change Historical quarantine artifacts.

Verify identical `prototype_unemittable_pairs()` and planner reconciliation,
the current CLI, Completion evaluation, enumeration tests and the import
boundary test. Update `ENVIRONMENT.md` in the same commit if retiring tests
changes the offline baseline. Savings are roughly 270 production lines,
not the whole legacy module count.

## 4. Define the bookable-slot rule once

`scenario_synthesis/journey_synthesis.py:334` selects available slots with the
same service as the appointment and a start after Fixture state's current
time. `agentsim/journey/scenario.py:424` independently checks those rules.

Share this small domain rule beside `FixtureState`. Keep validation's distinct
missing-slot, closed/past-slot and wrong-service explanations, and preserve
planning order. The existing fixed-seed Scenario-id test and Scenario
validation tests guard those behaviors. Savings are modest; the benefit is
preventing planning and validation from disagreeing. This carries forward the
open duplication finding in
`docs/solutions/journey-path-simplify-after-the-pipeline-exists.md`.

## 5. Two small follow-ups

- `agentsim/registry.py:84`: `VALIDATE_FOR_SUBMIT` repeats the counterparts in
  `SUBMIT_PAIRINGS`; repository code has no consumers of the former. Remove
  the unused mapping and stale cross-reference, or derive it from
  `SUBMIT_PAIRINGS` if compatibility must be retained.
- `scenario_synthesis/qualification.py:357`: `AdmissionDecision` stores both
  `admitted` and `status`, although `from_record` derives the former from the
  latter and all constructors provide equivalent values. Make `admitted` a
  property of `status`; preserve the serialized Admission fields and verify
  Admission decisions, record round trips and CLI behavior.

## Boundaries and verification

Keep the explicit evaluation sequence, separate Run/re-evaluation statuses,
retrieval/release safeguards, and Qualification evidence validation. Repeated
Qualification validation has different recovery and Rejection ledger effects;
merging it indiscriminately would change accounting. Large files alone do not
justify additional abstractions. The deferred generic refactoring plan was
not read or implemented. No mock behavior, Judge wording, contracts, committed
Scenario files or implementation code changed; no live calls were made.

Python 3.12.12 and `import readline` were verified. The initial sandboxed
baseline returned 901 passed, 1 failed and 29 errors because localhost socket
binding was prohibited. A full offline rerun with local socket access passed:
**931 passed in 133.83 seconds**, matching `ENVIRONMENT.md`. The reporting
discrepancy above was reproduced separately with existing offline doubles.

Compound: all findings from this review are recorded here; no vocabulary,
architecture or M/N/D ledger changes were made. Existing findings from prior
sessions remain in
`docs/solutions/journey-harness-review-findings-sessions-02-09.md`; this review
does not close them. Implementation and its regression-test changes remain
recommendations because the requested work was a review.
