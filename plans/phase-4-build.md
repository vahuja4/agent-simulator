# Phase 4 Build Plan

Scope: design doc §8 Phase 4 — async batch execution, explicit persona overlays,
deterministic failure clustering, replay emission, static reporting, and the
two-sided harness acceptance gate — under amendments 19–25. The generic plugin
refactor remains deferred until after Phase 5.

Done = one explicit calibration command runs both sides of the acceptance gate:
recall surfaces D1–D7 individually with the required source, and precision runs
the full 13-scenario defects-off library `N` configurable times with zero `fail`
or `error` outcomes (`task_incomplete` allowed). It leaves a resumable batch,
replays, clusters, a static Markdown report, and `acceptance.json`.

```sh
python scripts/run_calibration.py --acceptance --runs N \
  --concurrency C --out calibration_runs/phase4_acceptance
```

The command is an explicit live-calibration action using the existing PayCard
composition script. The library and default pytest suite remain offline.

## Step 0 baseline (completed before this plan)

- Snapshot: tag `phase-3-closed` at commit `9c74cd6`.
- Baseline record: `plans/phase-3-baseline.md` (216 offline tests passed and
  final 13/13 defects-off live evidence with the D1–D7 source table).
- Characterization-gap review: no tests were added. Existing tests already pin
  all six requested seams — tool-call sequences, trace serialization,
  assertion outcomes, criterion trigger on/off activation, scenario validation,
  and script replay — without a coverage gap.
- Design note: §9 records the future `paycard.selected_card` namespaced-
  observation shape; the current trace schema is unchanged.

## File tree

```text
agentsim/
  types.py                 CHANGE  artifact/cluster records + FailureRecord.from_dict
  orchestrator.py          CHANGE  expose structured degraded checks on RunResult
  persona_variation.py     NEW  validated persona-only overlays; base Scenario unchanged
  batch.py                 NEW  capped async runner, atomic artifacts, resume
  replay.py                NEW  Trace user turns -> serialized DSL replay
  clustering.py            NEW  deterministic membership; optional cached labels
  report.py                NEW  artifact-only static Markdown renderer
  acceptance.py            NEW  generic recall/precision expectation evaluator

calibration/
  phase4_acceptance.yaml   NEW  PayCard defect/scenario/source matrix as data
persona_variants/
  *.yaml                   NEW  explicit persona-only overlays
scripts/
  run_calibration.py       CHANGE  compose the one-command Phase 4 pipeline

tests/
  test_persona_variation.py
  test_batch.py
  test_replay_emitter.py
  test_clustering.py
  test_report.py
  test_acceptance.py
  test_phase4_acceptance.py
  test_phase4_imports.py
```

## Components and decisions

1. **Artifact and outcome contract.** `types.py` gains JSON round-trippable
   `BatchManifest`, `BatchRunRecord`, and `FailureCluster` records. A run record
   keeps `pass`, `fail`, `task_incomplete`, and `error` distinct and stores the
   complete `FailureRecord` data plus degraded checks. `orchestrator.py` exposes
   the latest deduplicated assertion degradation report; it does not change stop/
   fail semantics.

2. **Persona overlays.** Variation files may change only persona name/traits and
   carry a stable `variant_id`. Applying one returns a copy; journey, goal,
   knowledge, success criteria, max turns, and tool assertions are immutable and
   verified unchanged. The 13 committed scenario YAML files are never edited or
   silently mutated. Seeded overlay selection is deterministic and recorded.

3. **Async batch runner and resume.** `BatchRunner` accepts an injected generic
   async run callable, `Scenario`, model label, seed/run id, target metadata, and
   opaque defect flags. An `asyncio.Semaphore` enforces the configured cap. Stable
   run keys derive from the batch spec; each run atomically writes:

   ```text
   <batch>/
     manifest.json
     runs/<run-key>/
       run.json             outcome, failures, degraded checks, timings/metadata
       trace.json
       transcript.md
       replay.json
     clusters.json
     acceptance.json
     report.md
   ```

   The manifest records scenario, persona variant, defect flags, model, seed/run
   id, wall-clock timings, completion state, and LLM-call count for every run,
   plus the batch-wide LLM-call total. These counts are visibility only — no
   budgeting logic. A valid completed run directory is skipped on re-run;
   `--retry-errors` is explicit. Exceptions become `error` artifacts with an
   empty/error trace, never `fail`.

4. **Replay emitter.** For every failed run, map each recorded user turn to
   `user(text)` and each following agent turn to `agent()`, then serialize with
   the existing DSL. Each clustered FailureRecord links to that run's replay.
   A D1–D7-parameterized offline test loads one emitted replay per acceptance
   defect, re-runs it against the corresponding mock flag, and requires the exact
   failing tool-call sequence to match.

5. **Deterministic clustering.** Membership first partitions strictly by
   `(FailureRecord.source, FailureRecord.id)`. Within a partition, recursively
   flattened typed `data` tokens are compared with a documented deterministic
   similarity threshold and stable tie-breaking; cluster ids hash the canonical
   member keys. Ordering is size descending, then source/id/cluster id. An
   optional injected labeler may make exactly one call per unlabeled cluster;
   labels are cached in `clusters.json` by membership hash and never affect
   membership or rank.

6. **Static report.** `report.py` reads only the batch directory. `report.md`
   shows the four outcome counts separately, degraded checks, acceptance status,
   and ranked clusters. Every member links relatively to its transcript,
   `trace.json`, and `replay.json`; quoted rationale comes only from stored judge/
   assertion text. The only optional generated narrative is the cached cluster
   label.

7. **Two-sided acceptance gate.** The YAML matrix supplies domain-specific data;
   generic acceptance code contains no defect names, tool names, or journey ids.
   Recall runs each defect flag alone against its relevant scenario and requires
   `outcome=fail` plus:

   | Defect | Required FailureRecord |
   |---|---|
   | D1 same-turn | `assertion:validated_submit` |
   | D1 at-the-gate | `judge:explicit_confirmation` |
   | D2 | `assertion:refetch_after_card_switch` |
   | D3 | `judge:honest_failure` |
   | D4 | `judge:warning_acknowledged` |
   | D5 | `judge:card_disambiguation` |
   | D6 | `judge:journey_scoping` |
   | D7 | `judge:external_account_caveat` |

   Both D1 shapes and D2 use pinned scripted turns. The D1 same-turn and D2
   scripts delay judge checkpoints until the structural assertion has its full
   Phase 3 matched-pair evidence; the D1 at-the-gate script preserves the user
   turn between validate and submit and checkpoints the judge after the deviant
   submit. D3–D7 use pinned openings and the normal judge. Precision is all 13
   defects-off scenarios x `N` runs/persona variants: `pass` and
   `task_incomplete` are non-fail outcomes, but any `fail`, `error`, or degraded
   check fails the mock gate. Zero-degradation is matrix data, not a universal
   evaluator rule, because real-agent batches may legitimately degrade. Recall
   and precision are emitted and gated together; the command exits non-zero
   unless both pass.

8. **Coupling enforcement.** An AST import test covers every new `agentsim/`
   Phase 4 module. Internal imports are limited to `trace`, `types`, `scenario`,
   `script`, and `orchestrator` (plus the standard library); it rejects mock
   adapter/fixture/registry/assertion/criteria imports. A literal scan rejects
   PayCard tool names, card fields including `selected_card`, and `J1`–`J5` in
   those modules. PayCard composition remains only in the pre-existing calibration
   script and the acceptance data/tests; clustering, replay, and reporting key
   solely on generic artifacts.

9. **Calibration rule.** No judge wording change is planned. If implementation
   introduces or changes any judge criterion wording, it is live-verified with
   calibration artifacts before Phase 4 closes. Cluster-label prompts are
   optional reporting metadata and cannot alter verdicts or membership. No mock
   behavior change is in scope without separate approval.

## Build order

1. Artifact records + `RunResult.degraded_checks` and round-trip tests.
2. Persona overlays and immutability/seed tests.
3. Batch execution, atomic writes, outcome separation, concurrency, and resume.
4. Replay emission and D1–D7 tool-sequence reproductions.
5. Deterministic clustering and cached optional labels.
6. Artifact-only Markdown report.
7. Generic acceptance evaluator + calibration matrix + one-command composition.
8. Import-discipline test, complete offline suite, then the explicit live
   two-sided acceptance run and committed artifacts.

## Out of scope

Plugin extraction, generic policy engine, trace schema 2.0/observation migration,
HTTP/Sierra adapter, mock behavior changes, and any silent edits to committed
scenario semantics.
