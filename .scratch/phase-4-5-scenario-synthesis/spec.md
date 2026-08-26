Status: approved
Triage: ready-for-agent

# Phase 4.5 scenario synthesis

## Problem Statement

The committed scenario-synthesis prototype can enumerate, realize, and dry-run J1 material, but its schema and mutable manifest do not represent the reviewed Coverage-cell model, distinguish qualified evidence from historical output, or support auditable admission and regeneration. Phase 4.5 needs an executable contract for productizing that prototype without reopening the decisions already recorded for synthesis coverage, taxonomy, eligibility, fitness, or admission.

## Normative sources

This specification adds mechanics only. The implementation must apply, rather than restate or reinterpret:

- ADR 0001 for the prototype baseline and historical-candidate quarantine.
- ADR 0002 for Coverage cells and coverage obligations.
- ADR 0003 for Persona archetypes and Same-cell equivalence.
- ADR 0004 for eligibility, exclusion reasons, BLOCKED, and UNCOVERED.
- ADR 0005 for Complication values, applicability, and definition tests.
- ADR 0006 for Knowledge-level evidence and judge-robustness handling.
- ADR 0007 for Fitness-target mapping, admission evidence, repetition semantics, library limits, and the Phase 4.5 gate.
- `CONTEXT.md` for domain vocabulary and repository invariants.
- The “Phase 4.5 completion claim” in `docs/plans/phase-4.5-spec-input.md` as the complete acceptance criteria, incorporated by reference.

If generated code or data disagrees with one of these sources, fail closed and report the disagreement. Do not infer a replacement rule.

## Requirements

### 1. Ownership and locations

1. `scenario_synthesis/` remains the implementation package. Existing enumeration, validation, realization, and dry-run behavior must be audited and evolved in place.
2. `scenarios/` remains the curated Scenario library. A synthesized Scenario must never be written there.
3. `generated_scenarios/` is the read-only historical quarantine. Phase 4.5 may inspect it for the prototype eligibility reconciliation but must not use it as a candidate source, evidence source, admission source, or output root.
4. Reviewed synthesis inputs live under `scenario_synthesis/contracts/`:
   - `persona-archetypes.yaml` owns the archetype contracts and curated-Scenario mapping.
   - `complication-applicability.yaml` owns the reviewed precondition matrix.
   - `pair-exclusions.yaml` owns reviewed pair exclusions.
   - `fixture-state-classes.yaml` owns fixture-state equivalence classes.
   - `fitness-targets.yaml` owns the mapping from Fitness targets to defect configuration and expected structured failure.
5. Journey graphs remain under `scenario_synthesis/procedures/`. Their edges must have stable identifiers; a path is an ordered list of those identifiers, not a free-form label.
6. Operational configuration lives at `scenario_synthesis/config.yaml`. It references reviewed inputs and prompt templates by path and pins all limits and model identifiers used by a qualification run. It contains no credentials or environment-specific output paths.
7. Prompt templates live under `scenario_synthesis/prompts/` and are version-controlled text files. Configuration snapshots record their SHA-256 hashes.
8. New durable outputs live under `synthesized_scenarios/`:
   - `candidates/<candidate-id>/` contains one immutable candidate bundle.
   - `runs/<qualification-id>/` contains one immutable qualification bundle.
   - `library/` contains only admitted synthesized Scenario YAML.
   - `ledger/rejections.jsonl` is the append-only rejection ledger.
   - `reports/<report-id>/` contains one coverage-report bundle.
9. Human-reviewed contracts, admitted library files, terminal candidate records, qualification evidence used for admission, the rejection ledger, and completion reports are repository evidence and must be committed. Transient API responses may be omitted only when their normalized content and hash are retained in the corresponding bundle. If evidence volume makes full committed bundles impractical, the committed form may instead contain normalized summaries and content hashes while the full bundles live under the gitignored `.artifacts/scenario_synthesis/` root. The config snapshot and report record which retention form was used and the full-bundle location. Ledger hashes remain the authoritative evidence identity in both forms; reducing retention must not alter admission evaluation, denominators, or rejection history.
10. The authoritative `persona-archetypes.yaml` introduction and the approved `j1-happy-path` Persona correction must be one atomic change. No other curated Scenario content changes as part of that correction.

### 2. Reviewed-contract schemas

1. Every reviewed contract is strict: it has a positive integer `schema_version`, rejects unknown fields, uses stable IDs, and has a canonical SHA-256 content hash computed from normalized parsed content rather than source formatting.
2. `persona-archetypes.yaml` records each archetype ID, its normative ADR reference, any external behavior-contract reference, and the curated-Scenario-to-archetype mapping. It does not duplicate behavioral prose from the referenced decision.
3. `complication-applicability.yaml` records, per Complication ID, the required journey edge/event IDs and fixture predicates, its review state, and review evidence. Non-applicability is represented through the ADR 0004 exclusion artifact, not by silently dropping combinations.
4. `pair-exclusions.yaml` records `axis_a`, `value_a`, `axis_b`, `value_b`, the closed ADR 0004 reason code, rationale, evidence references, reviewer, and review date. Entries are unique after canonical axis/value ordering. A reduction in obligations is invalid unless the changed entry is explicitly reviewed.
5. `fixture-state-classes.yaml` records each class ID, the scenario-relevant predicates defining it, and the concrete Fixture bindings that are members. Every binding selected by synthesis resolves to exactly one class for the applicable predicates.
6. `fitness-targets.yaml` records stable target and shape IDs, the defect toggle set, the expected structured failure source and ID, applicability predicates, and the ADR reference. Code validates these entries against the mock configuration and registered assertions/judge criteria; it does not maintain a second mapping.
7. Every contract that depends on a journey graph, Fixture domain, taxonomy, or Fitness-target mapping records the dependency hashes against which it was reviewed. A stale dependency makes coverage planning and qualification invalid until affected entries are re-reviewed.

### 3. Coverage-cell and blueprint schema

1. Replace the prototype’s legacy strata as the qualification identity with a strict, versioned blueprint schema representing the reviewed domain model. Compatibility readers may load historical blueprints only for reconciliation; they may not upgrade them into candidates implicitly.
2. A blueprint contains:
   - `schema_version` and `blueprint_id`;
   - `cell_id`;
   - the six canonical Coverage-cell axes: `journey_path_id`, `persona_archetype`, `knowledge_level`, `complication`, `fixture_state_class_id`, and nullable `fitness_target_id` plus its shape ID when applicable;
   - the ordered journey-edge IDs;
   - concrete Fixture bindings and structured Goal facts;
   - required assertions and judge-criterion IDs;
   - `max_turns`;
   - generation provenance.
3. `cell_id` is the full SHA-256 hash, with a readable prefix, of the canonical six-axis tuple. Surface fields, candidate ordinal, and timestamps are excluded. The same function is the sole implementation of Same-cell equivalence.
4. `blueprint_id` is a content-derived identifier over all semantic blueprint fields except provenance timestamps. Any semantic change creates a new blueprint.
5. Generation provenance contains `generator_version`, `config_hash`, and a `source_hashes` mapping for the journey graph, Fixture version, archetype contract, Complication applicability contract, pair-exclusion contract, fixture-state-class contract, and Fitness-target contract.
6. The generator selects all axes, Fixture bindings, Goal facts, assertions, criteria, and limits before realization. The realization provider receives those values as immutable constraints and may return only narrative surface fields admitted by its response schema.
7. Blueprint validation checks contract hashes, stable IDs, path continuity, applicability, Fixture membership, the Sealed-world rule, required checks, and Scenario-loader compatibility before realization is allowed.

### 4. Scenario schema and identity

1. Extend the existing strict Scenario loader with an optional top-level `synthesis` mapping. Its absence means the Scenario is curated; it is never inferred from a filename or description. Curated files need not be mechanically rewritten except for the separately approved atomic correction.
2. `synthesis` is required for every synthesized Scenario and contains only `schema_version`, `origin` (fixed to `synthesized`), `candidate_id`, `blueprint_id`, `cell_id`, and the blueprint content hash.
3. Runtime Scenario fields remain the existing Scenario contract. Coverage axes and qualification status are not copied into narrative strings and are not trusted from LLM output; they resolve through the referenced immutable blueprint and records.
4. A synthesized Scenario name is stable and content-derived. It must not collide with a curated name or another synthesized Scenario with different content.
5. The loader rejects unknown synthesis fields, missing referenced identity, malformed hashes, and an `origin` other than `synthesized`. Library validation additionally verifies that references exist and hashes match.
6. Loading a synthesized Scenario through the existing loader must produce the same runtime Scenario behavior as an equivalent curated file; provenance is metadata and cannot alter simulator, assertion, or judge behavior.

### 5. Configuration and snapshots

1. `scenario_synthesis/config.yaml` is strict and versioned. It contains:
   - reviewed-contract and prompt-template paths;
   - generator and realization versions;
   - simulator and judge model identifiers;
   - realization token budget and retry bound;
   - admission repetition and replacement bounds;
   - Same-cell library cap;
   - concurrency and per-command cell limits;
   - output-root layout version;
   - the default-off model-family enforcement setting required before Phase 5.
2. Values fixed by ADR 0007 and the specification input are represented once in this configuration and validated against code invariants; command-line flags may narrow a run but may not weaken an admission rule.
3. Each coverage report and qualification bundle contains `config-snapshot.yaml`, the snapshot hash, repository revision when available, dirty-state indicator, model identifiers, prompt hashes, Fixture version/hash, and every reviewed-contract hash. Environment variables may supply credentials only and must not change the recorded semantic configuration invisibly.
4. Resuming work requires an exact snapshot-hash match. A changed snapshot starts a new qualification ID and cannot append repetitions to earlier evidence.

### 6. Candidate lifecycle

1. Coverage planning deterministically enumerates obligations from the reviewed contracts before candidate production. It emits all covered, excluded, BLOCKED, and UNCOVERED obligations; generator reachability never defines eligibility.
2. A realization attempt is not a candidate until its output passes the structured response schema, fact-equivalence checks, blueprint validation, and the Scenario loader. Failed production attempts are recorded but do not consume a Fitness-regeneration slot; simulator compliance is evaluated during qualification.
3. Candidate production makes at most two realization calls for one blueprint in one command: the initial call and one corrective retry. If both fail, the cell remains UNCOVERED, the failure is recorded, and the command does not loop. A later retry requires a new production command and a new realization-attempt ID.
4. A candidate receives ordinal `0` for the initial candidate and `1` or `2` for replacements. `candidate_id` combines `cell_id`, the ordinal, and a hash of the blueprint plus normalized realized Scenario. A candidate bundle contains `blueprint.yaml`, `scenario.yaml`, `production.json`, and, once terminal, `terminal.json`.
5. Candidate bundle files are immutable after their hashes are recorded. Qualification output is written to a separate run bundle; terminal status is appended once. A rejected candidate is never edited, retried, or relabeled as admitted.
6. Qualification uses the existing Scenario loader and the existing `run_scenario`/batch boundary. It creates the repetitions and configurations required by ADR 0007, preserving each transcript, trace, deterministic Assertion result, Judge ruling, simulator-compliance ruling, and structured failure.
7. Every repetition records its repetition index, simulator and judge identifiers, prompt hashes, Fixture version, defect toggles, transcript/trace locations and hashes, termination, outcome, degradation/errors, and exact structured failures.
8. Admission evaluation is a pure operation over a complete qualification bundle. Apply the fitness and detection-unproven rules by reference to ADR 0007. An error, missing artifact, degraded check, incomplete outcome, extra failure, or configuration mismatch fails closed and contributes no evidence.
9. On rejection, append a ledger event, write the candidate terminal record, and generate the next ordinal from the shared factory if budget remains. Candidate-specific repair is forbidden. Once ordinal `2` is rejected, the cell remains UNCOVERED and is marked `regeneration_exhausted: true` in reports.
10. Admission atomically writes the terminal record, admission decision, and byte-identical Scenario YAML to `synthesized_scenarios/library/`. Before the rename, revalidate the bundle, Same-cell cap, name uniqueness, and contract/config hashes. Interrupted staging files confer no admission.
11. Re-running an operation with the same IDs is idempotent: verified completed artifacts are reused, partial artifacts are quarantined as corrupt, and no ledger event or qualification repetition is duplicated.
12. Concurrent writers are prohibited per cell and per append-only ledger. Use an exclusive repository-local lock with owner, command, and start-time metadata; stale-lock removal is an explicit operator action and is itself logged.

### 7. Rejection ledger

1. `rejections.jsonl` is UTF-8 JSON Lines with one canonical JSON object per failed production attempt or rejected candidate. Existing lines are never reordered, edited, or removed.
2. Each event contains `schema_version`, `event_id`, UTC timestamp, `subject_type`, realization-attempt or candidate ID, `cell_id`, candidate ordinal when assigned, lifecycle stage, stable reason code, human-readable detail, evidence paths and hashes, config snapshot hash, contract hashes, and replacement predecessor/successor IDs when known.
3. Reason codes distinguish schema failure, fact-equivalence failure, contract drift, simulator noncompliance, defects-off failure, expected-failure mismatch, unrelated failure, degraded/error/incomplete evidence, duplicate/cap conflict, and operator cancellation. Reports group by reason code and retain the underlying event IDs.
4. Ledger validation verifies canonical JSON, unique event IDs, referential integrity, monotonic file order, and content hashes. Validation failure blocks admission and completion reporting.

### 8. Coverage and completion reporting

1. A report bundle contains authoritative `coverage.json`, derived `coverage.md`, and the exact `config-snapshot.yaml`. Markdown is regenerated from JSON and is never an independent data source.
2. `coverage.json` contains:
   - report/schema IDs and generation time;
   - all snapshot and reviewed-artifact hashes;
   - eligible-axis, eligible-pair, journey-edge, known-defect, and eligible-cell denominators;
   - one record per obligation with stable ID, kind, axes, status, admitted Scenario IDs, exclusion entry or BLOCKED reason, rejection event IDs, and `regeneration_exhausted`;
   - separate aggregate counts for covered, BLOCKED, UNCOVERED, excluded, and regeneration-exhausted obligations;
   - admitted counts by Coverage-cell axis and Fitness target;
   - detection-unproven count and IDs without removing them from the denominator;
   - curated and synthesized distributions reported separately, including the curated baseline reference;
   - completion-claim condition results with evidence links.
3. Excluded obligations appear in their own section and never enter covered/BLOCKED/UNCOVERED totals. BLOCKED and UNCOVERED are never pooled. Regeneration exhaustion is a boolean refinement of UNCOVERED, not a fifth eligibility state.
4. `coverage.md` presents the same denominators, status counts, gaps, exclusions, rejection summary, definition-test status, and acceptance-condition evidence in reviewable tables. Every total links or keys back to JSON records.
5. The prototype eligibility reconciliation is emitted as a named report section and machine-readable obligation records. Every prototype-unemittable pair resolves to exactly one classification allowed by ADR 0004.
6. A completion report may claim Phase 4.5 complete only by evaluating the incorporated completion claim against stored evidence. Manual prose cannot override a failed or unknown condition.

### 9. Operational commands and bounds

1. Provide one synthesis command surface with explicit subcommands for `validate-contracts`, `plan`, `produce`, `qualify`, `report`, and `check-completion`. Internal modules may remain separate; users must not assemble lifecycle states by editing files.
2. `validate-contracts`, `plan`, `report`, and validation tests are offline and make no LLM calls. `produce` and `qualify` require an explicit `--live` flag; absence of the flag fails before client construction.
3. Live commands require an explicit cell selector or configured positive `--max-cells`. They print the maximum planned realization and Episode counts and the snapshot hash before execution. Concurrency and cell bounds come from configuration and cannot be exceeded by flags.
4. `qualify` refuses historical, unvalidated, already terminal, over-budget, or snapshot-mismatched candidates. It enables exactly the target defect configuration for targeted repetitions and verifies the effective mock configuration before the first Episode.
5. Signal interruption completes the current atomic write, records cancellation where applicable, and exits nonzero. Resume never treats cancellation or a partial repetition as evidence.
6. No command changes the deterministic mock’s behavior, Judge criterion wording, or committed Scenario YAML except the separately approved `j1-happy-path` correction. Live calibration is outside these commands.
7. All Python entrypoints and tests use the repository `.venv` contract in `AGENTS.md` and add no dependency.
8. The first live batch contains exactly five distinct cells: one for each Complication identified as unpopulated in the specification input, plus one low-Knowledge cell. Every cell receives full qualification; a production-only or partial-qualification batch does not satisfy this rollout stage.
9. After that batch, all further `produce` operations are blocked pending human review of the definition-test evidence for the four Complications and the judge-robustness evidence for the low-Knowledge cell. Qualification, reporting, and evidence inspection for the initial batch remain available while the block is active.
10. The review decision is committed at `synthesized_scenarios/reviews/initial-live-batch.yaml`. It identifies the batch and five cells, binds to their qualification and ledger hashes, records each definition ruling and the low-Knowledge judge-robustness ruling, and contains reviewer, review date, and an `approved` or `changes_required` decision. Only `approved` unlocks further production; changed evidence invalidates the approval by hash mismatch.

## Testing Decisions

1. The primary seam is the public synthesis command/service operating against a temporary artifact root, a stub realization provider, and a stubbed existing `run_scenario` boundary. Tests assert externally visible files, lifecycle state, admission decisions, and reports rather than helper calls.
2. Extend the existing `test_scenario_synthesis_phase*.py` prior art instead of creating a parallel harness. Reuse `tests/test_scenario.py` for strict Scenario schema/loader behavior and the existing batch/orchestrator test doubles for qualification evidence.
3. Contract tests cover strict parsing, canonical hashes, stale dependency detection, pair canonicalization, graph/path IDs, fixture-state membership, and reconciliation completeness.
4. Lifecycle tests cover successful admission, detection-unproven admission, every fail-closed evidence class, both replacement transitions, exhaustion remaining UNCOVERED, immutable rejected bundles, idempotent resume, interrupted writes, lock contention, and Same-cell cap enforcement.
5. Reporting tests build a small fixed obligation universe containing covered, BLOCKED, UNCOVERED, excluded, regeneration-exhausted, and detection-unproven examples; they assert JSON denominators and exact Markdown projection from that JSON.
6. Historical-quarantine tests prove that existing `generated_scenarios/` candidates and dry runs cannot satisfy admission, fitness, or completion checks.
7. The first live qualification for each Complication named by the specification-input follow-up is a human review gate over its stored transcript, trace, compliance ruling, and qualification result. The reviewer rules on its boundary against neighboring concepts; ambiguity blocks admission and further production until the applicable contract receives a reviewed ruling. Offline tests verify enforcement and evidence binding for this gate but do not substitute for the live review.
8. The first live low-Knowledge qualification is a human review gate over its stored judge-robustness evidence. Instability enters the N-series/calibration workflow without changing criterion wording or silently admitting the candidate. Offline tests verify enforcement and evidence binding for this gate but do not supply the judge-robustness ruling.
9. The final offline suite includes the full curated suite and must remain green. No ordinary test or completion check performs live LLM calibration or acceptance.

## Acceptance Criteria

The “Phase 4.5 completion claim” section of `docs/plans/phase-4.5-spec-input.md` is incorporated by reference as the complete acceptance criteria. The completion report defined above must evaluate each condition and link it to durable evidence; this specification adds no substitute or additional product-level criterion.

## Out of Scope

- Reconsidering any decision in ADRs 0001–0007.
- Coverage-guided generation, simulator-diversity admission, pruning, or Phase 5 simulator migration/re-qualification.
- Compound Complications or additions to the closed axes.
- Changes to deterministic mock behavior or Judge criterion wording.
- The deferred generic refactoring plan.
- Treating historical prototype output as qualification evidence.

## Implementation-planning gate

This specification is approved. Propose and obtain review of the implementation slice order before creating implementation tickets or changing implementation code.
