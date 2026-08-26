# Phase 4.5 scenario-synthesis grilling handoff

> Historical handoff: its open frontier was completed in
> `docs/plans/phase-4.5-grilling-handoff-2.md`. Use
> `docs/plans/phase-4.5-spec-input.md` for the closed design.

## Purpose

Continue the design grill for **Phase 4.5: automatic scenario synthesis** exactly where the prior session stopped. Work one decision area at a time, present concrete options and a recommendation, record each settled decision immediately in `CONTEXT.md`, an ADR, or a focused report, and stop when the decision tree is exhausted. Specification and implementation planning belong to later sessions.

## Start here

Read these before asking the next question:

1. `AGENTS.md` and `CONTEXT.md`.
2. `plans/phase-3-baseline.md`, `plans/phase-4-build.md`, and `plans/phase-4-handoff.md`.
3. `docs/solutions/simulator-model-luna.md`.
4. `.agents/skills/grill-with-docs/SKILL.md`, then its required `grilling` and `domain-modeling` skills.
5. The decision records and report listed under **Artifacts** below.

The committed `scenario_synthesis/` package and its August 17–18 phase notes are an existing prototype, not a greenfield proposal and not the Phase 4.5 specification. Do not browse old calibration transcripts unless a later question makes them necessary.

## Feature intent

Grow coverage beyond hand-authored YAML by synthesizing candidates that use the same Scenario schema and batch machinery as curated Scenarios. The intended starting paradigm is reviewed, code-defined combination sampling; an LLM may realize surface text but may not invent combination structure or fixture facts. Every admitted synthesized Scenario must prove defect sensitivity against the deterministic mock and avoid false alarms with defects disabled. Synthesized provenance and results remain distinguishable from the curated library. The harness adds no dependency.

Research alternatives remain context rather than decisions: IntellAgent-style policy/combination sampling, FLARE-style coverage guidance, and staged candidate QC. Luna's low episode cost makes per-candidate live QC affordable, while its migration demonstrated that simulator diversity itself can expose latent bugs.

## Settled decisions

### Area 1 — baseline

Productize and audit the existing `scenario_synthesis/` prototype. Historical generated candidates remain quarantined and receive no fitness credit; they must qualify from scratch under Phase 4.5. Earlier synthesis plans and notes are historical evidence only. Full rationale: `docs/adrs/0001-productize-existing-scenario-synthesis-prototype.md`.

### Area 2 — coverage

Use constrained interaction coverage. A Coverage cell is the semantic tuple of journey path, Persona archetype, Knowledge level, Complication, fixture-state equivalence class, and Fitness target; surface realization is excluded. Require every eligible axis value and eligible pairwise interaction, plus independent coverage of every approved journey edge and known planted-defect class. Report complete valid-cell coverage when tractable, but do not make the full Cartesian product a universal gate.

Pair eligibility is an explicit reviewed artifact. Every excluded pair needs a recorded justification; exclusions cannot silently erase coverage obligations. Fitness-target coverage is a closed-world claim over known planted-defect classes. Coverage-guided generation is the named future approach for discovering behavior outside that set.

Two Scenarios are Same-cell equivalent exactly when all Coverage cell axes match. This definition is shared with near-duplicate control. Full rationale: `docs/adrs/0002-use-constrained-interaction-coverage-for-synthesis.md`.

### Areas 3–4 — taxonomy

Use exactly one primary Persona archetype per Scenario, with no secondary archetypes:

- **Cooperative:** supplies requested information and accepts satisfactory guidance; the control archetype.
- **Pressure:** rushes past a gate for an in-scope action the agent is willing to perform; probes confirmation skipping. Reference the confirmation-gate behavior in `docs/solutions/simulator-model-luna.md` without restating it.
- **Vigilant:** challenges inconsistent, surprising, or insufficiently explained information; probes truthfulness and clarification.
- **Persistent:** re-attempts after refusal or an unsatisfactory answer; probes wear-down compliance and repetitive loops.

The Pressure/Persistent boundary is **speed against procedure versus attrition against refusal**. Admit a new archetype only when it can plausibly make the agent fail differently; temperament synonyms do not qualify.

Knowledge level is an independent low/medium/high axis. Low knowledge may use an incorrect term for a real fixture fact—for example, saying “minimum” while referring to the statement balance—to test clarification. Under the Sealed-world rule, wrong labels for real facts are allowed only at low knowledge; invented facts are forbidden at every level.

A synthesized Coverage cell has zero or one Complication. Zero-Complication baselines are mandatory controls and false-alarm detectors. Compound complications are never synthesized. Revisit one only when a Phase 5 real-agent failure exhibits an interaction effect that no single-Complication Scenario reproduces; then hand-design that specific compound Scenario with its own success criteria.

Corrected classifications:

- `changes_mind_once` is the mid-conversation-correction Complication.
- Deliberately answering only as asked or partially disclosing required facts is the underspecification Complication, not Persona identity.
- Terseness is surface style.
- Confused-customer behavior belongs to low Knowledge level.
- Victor's outcome-confirmation request belongs to Goal and success criteria.

The curated mapping is verified in `docs/reports/persona-archetype-mapping.md`. It found one mismatch: `j1-happy-path` says both “everything upfront” and “answers one question at a time.” It also found that the current schema declares no Knowledge level, so retroactive level assignments would be invention. Full taxonomy rationale: `docs/adrs/0003-use-reviewed-behavioral-taxonomies-for-synthesis.md`.

### Area 5 — fitness admission and rejection

Use a strict two-sided **N=3** contract per candidate:

- With all defects OFF, all three repetitions must be `pass`; `task_incomplete` is not fitness evidence.
- With exactly the targeted defect ON, all three repetitions must contain the exact expected structured failure and no unrelated failure.
- Simulator compliance must pass on both sides.
- Errors, degraded checks, and incomplete outcomes provide no fitness evidence.

Reject a failed candidate from library admission without hand-fixing its prose or semantics. Retain an append-only rejection ledger containing the candidate identity, Coverage cell, failure stage/reason, model/configuration identity, and attempt history. The cell remains visibly uncovered.

Apply the **repair-the-factory rule**: systematic or repeated rejection is evidence against the generator, taxonomy, constraint model, realization prompt, or validator. Correct that shared source and synthesize a new candidate; do not patch the rejected instance into passing.

The prototype's surface-realization validation budget is an initial attempt plus one retry, then fail closed. Separately, a Coverage cell receives at most **K=2 fresh replacement candidates after the initial candidate fails completed two-sided fitness**: at most three fitness-evaluated candidates per cell. Each fresh candidate retains its own realization-format retry; that retry is not a regeneration.

If all three candidates are rejected, classify the cell as **uncovered—regeneration exhausted**. Exhaustion neither waives the coverage obligation nor converts the cell into an eligibility exclusion. Further attempts require a reviewed repair to the shared factory, after which new candidates may be synthesized; the append-only rejection history remains evidence. Area 5 is closed.

### Area 6 — pair eligibility

Every cross-axis pair is eligible by default. Exclusion is permitted only for
one of four reviewed reasons: contradiction between approved value contracts,
journey-graph impossibility, fixture-domain impossibility, or non-applicability
under an approved axis contract. Cost, expected value, generator/model limits,
and missing implementation cannot erase an obligation.

Eligible gaps remain visibly distinct: **BLOCKED** is unrealizable by the
current implementation or generator for a recorded reason and represents
engineering debt; **UNCOVERED** is realizable but lacks an admitted Scenario and
represents pipeline backlog. Reports must not pool them.

The exclusion artifact records each pair, reason code, rationale, and evidence;
coverage reports bind to its version or hash. Coverage-reducing changes require
explicit review, and affected exclusions are re-reviewed when their source
taxonomy, graph, fixtures, or fitness mapping changes. Before any Phase 4.5
acceptance claim, the prototype's generator-derived eligibility must be
reconciled so every pair it cannot emit is explicitly excluded, BLOCKED, or
eligible and owed. Full rationale:
`docs/adrs/0004-default-pairs-to-eligible-with-reviewed-exclusions.md`.

### Area 7 — Complication taxonomy and applicability

Use the closed nine-value axis: none, underspecification, mid-conversation
correction, goal shift, multi-intent turn, false premise, out-of-scope drift,
channel noise, and ambiguous reference. Every Scenario maps to exactly one
value; synthesized Scenarios never combine non-none values.

Journey applicability is defined by a reviewed precondition matrix. Missing
semantic support is an approved non-applicability exclusion; missing generator
support is BLOCKED. False premise requires a real Fixture fact about which the
user holds an actual incorrect belief. Procedure branches, validation outcomes,
tool failures, and fixture conditions are not conversational Complications.
Coverage reports bind to both the pair-exclusion artifact and applicability
matrix versions or hashes under the same coverage-reduction review contract.

The 13-scenario mapping is recorded in
`docs/reports/complication-taxonomy-mapping.md`. It confirms ambiguous reference
as distinct from underspecification and classifies the correctly understood
below-minimum J3 warning as none. The curated distribution is 9 none / 4
non-none. Goal shift, multi-intent turn, out-of-scope drift, and channel noise
have zero curated instances and are designed but not yet empirically validated;
their first synthesized realization is also a definition test requiring any
boundary ambiguity to be ruled on before admission. Full rationale:
`docs/adrs/0005-use-a-closed-complication-taxonomy.md`.

## Artifacts

- `CONTEXT.md` — Coverage cell, Same-cell equivalence, Fixture state, Fitness target, archetypes, Knowledge level, Sealed-world rule, and corrected Complication vocabulary.
- `docs/adrs/0001-productize-existing-scenario-synthesis-prototype.md`
- `docs/adrs/0002-use-constrained-interaction-coverage-for-synthesis.md`
- `docs/adrs/0003-use-reviewed-behavioral-taxonomies-for-synthesis.md`
- `docs/adrs/0004-default-pairs-to-eligible-with-reviewed-exclusions.md`
- `docs/adrs/0005-use-a-closed-complication-taxonomy.md`
- `docs/reports/persona-archetype-mapping.md`
- `docs/reports/complication-taxonomy-mapping.md`
- `docs/plans/phase-4.5-grilling-handoff.md` — this continuation index.

These documentation changes are uncommitted. Preserve the user's unrelated untracked `.pptx` files. The corrected domain taxonomy must be committed atomically with the eventual authoritative taxonomy-artifact change; the current prototype's `scenario_synthesis/persona_traits.yaml` still reflects the superseded trait-dimension model and is not authoritative.

## Recorded follow-up — do not act in this grilling session

Fix the `j1-happy-path` Persona contradiction identified in
`docs/reports/persona-archetype-mapping.md`. This requires an explicitly
approved edit to the committed Scenario YAML and must be bundled atomically with
the authoritative taxonomy-artifact commit. Do not perform the edit while
grilling Phase 4.5.

## Historical ungrilled decision areas

This was the frontier at this handoff. It is retained as session history and is
now closed by the second handoff and ADRs 0004–0007.

1. **Area 5 closure:** numeric post-fitness regeneration budget per Coverage cell; ledger retention and terminal treatment of an exhausted cell.
2. **Pair eligibility:** default-eligible rule, permissible exclusion reasons, approval/versioning, and treatment of currently unrealizable pairs.
3. **Complication taxonomy:** exact finite values, journey applicability, and decomposition of procedure paths/tool outcomes versus conversational Complications.
4. **Knowledge-level behavior:** operational distinctions among low/medium/high beyond low-level term misuse, and eligibility constraints with journeys/personas.
5. **Fitness-target mapping:** exact D1–D7 target/source contracts, targets with multiple failure shapes, and handling Coverage cells with no applicable known defect.
6. **Multi-simulator fitness:** Luna-only versus multiple simulator models; model-family separation, Phase 5 migration, and whether diversity is admission evidence or a separate robustness tier.
7. **Repetition and seed semantics:** what `N=3` identifies, because synthesis seeds are reproducible but simulator seeds do not control model stochasticity; recording model snapshots and nondeterministic repetitions.
8. **Near-duplicate control and library budget:** treatment of Same-cell-equivalent surface variants, cross-cell semantic similarity, per-cell caps, total size, replacement, and pruning.
9. **Candidate lifecycle:** quarantine, qualification, promotion, immutability, requalification after graph/fixture/model changes, and the boundary between generated and curated Scenarios.
10. **Provenance and schema:** provenance fields in the shared Scenario schema, hashes/versions required, and compatibility for existing curated YAML.
11. **Reporting:** separate curated/synthesized pass rates, denominators, confidence/pooling rules, rejection and uncovered-cell reporting, and aggregate-report safeguards.
12. **Coverage-guidance trigger:** measurable blind-spot condition that justifies adding FLARE-style guidance, plus what feedback may influence generation without obscuring the denominator.
13. **LLM realization boundary:** permitted surface fields, semantic-equivalence enforcement, Sealed-world validation including low-knowledge wrong terms, and prompt/model provenance.
14. **Pressure behavior under QC:** interaction with confirmation targets, compliance validation, and whether all three repetitions must exercise the prescribed pressure sequence.
15. **Configuration ownership:** where taxonomy, pair constraints, journey graphs, fitness mappings, budgets, and model choices live; review and drift rules.
16. **Phase 4.5 acceptance gate:** required journeys, coverage thresholds, qualification counts, cost/error tolerances, offline/live evidence, and the precise completion claim.
17. **Operational bounds:** candidate-generation budget, live-call authorization, concurrency/resume behavior, artifact retention, and failure recovery.

## Suggested skills

- **`grill-with-docs`** — resume the one-area-at-a-time interview and record decisions inline.
- **`grilling`** — maintain the dependency-aware design tree and challenge silent assumptions.
- **`domain-modeling`** — reconcile canonical terms with `CONTEXT.md` and create ADRs only for durable trade-offs.

Do not invoke a specification or implementation-planning skill in the continuation session. Stop after the grill reaches an empty frontier and the user confirms shared understanding.
