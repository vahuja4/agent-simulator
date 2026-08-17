# Scenario Synthesis — Lean Phased Plan

**Status:** Plan for implementation; each phase sized for one coding-agent session
**Date:** 2026-08-17
**Supersedes scope of:** `plans/automatic-scenario-synthesis-recommendation.md` (the
recommendation stands as research context; this plan cuts it down to what gets built)

## Ground rules for every phase

- Each phase is one coding-agent session. Every phase spec below includes a **read
  boundary** — the only files the agent may read — to keep context utilization low.
  Everything else in the repo (calibration transcripts, old plans, build docs) is
  off-limits per `AGENTS.md`.
- Each phase ends with: offline tests passing (`.venv/bin/python -m pytest`), git clean,
  and a short `plans/synthesis-phase-N-notes.md` recording decisions and any gate results.
- All repository invariants hold throughout: no mock changes, no judge-wording changes,
  no mutation of `scenarios/` or committed fixtures, no live LLM calls from tests.
- New code lives in `scenario_synthesis/` (package) and `generated_scenarios/` (output).
  Nothing under `agentsim/` is modified in any phase except where a phase explicitly
  says so.

## What is deliberately cut (and the trigger to revisit)

| Cut | Why | Revisit when |
|---|---|---|
| Weighted policy graph + random walks | Plain compatibility lists suffice at this scale | Policy count > ~20 or combinations feel arbitrary |
| FLARE-style mutation/evolution loop | Blueprint space is likely enumerable; enumeration + stratified sampling is simpler and fully auditable | Phase 2 sizing shows space ≫ what you can enumerate/run |
| New oracle language (`expected_final_state` solver) | The existing closed `tool_assertions` vocabulary + judge criteria already are the oracle | An assertion you need doesn't exist — then add one assertion type, with tests, not a new language |
| Fixture-state synthesis / overlays | Bind to existing `fixtures/paycard.py` entries only | An interesting blueprint is unsatisfiable with current fixtures |
| Coverage-guided seed selection | Coverage is *recorded* from Phase 4, but never drives selection | Enumeration is descoped (see above) |
| LLM-drafted graphs or weights | Graphs are hand-authored from approved journey definitions | Never (review-only artifacts) |

---

## Phase 1 — Blueprint schema, J1 procedure graph, validator (no LLM)

**Goal:** A `Blueprint` dataclass, a hand-authored J1 procedure graph, and a
deterministic validator. No generation yet.

**Build**

- `scenario_synthesis/blueprint.py`: frozen dataclass + YAML load/dump. Fields:
  `id, journey, procedure_path, policies, fixture_bindings (card/account last-fours),
  goal_facts, perturbations (type + position), tool_assertions (existing closed vocab),
  max_turns, provenance (generator_version, seed, graph_hash, fixture_hash)`.
- `scenario_synthesis/procedures/j1.yaml`: nodes = semantic steps (disclose, select
  card, fetch options, validate, confirm, submit, handle failure, terminate); edges
  carry: required registry tools, applicable policies, valid perturbation points, and
  worst-case turn cost (so `partial_disclosure`-style inflation is priced in, not
  nominal path length).
- `scenario_synthesis/policies.py`: policy IDs with journey applicability, required
  fixture predicates, mapped `tool_assertions`, and plain compatible/incompatible
  lists. Start with four: `explicit_confirmation`, `tool_output_truth`,
  `card_switch_resets`, `disambiguate_last_four`.
- `scenario_synthesis/validator.py`: rejects a blueprint unless (1) path is connected
  and terminates in the J1 graph, (2) every tool exists in `agentsim/registry.py`,
  (3) every binding resolves in `fixtures/paycard.py` and satisfies the path's
  predicates, (4) every policy maps to at least one assertion or judge hook,
  (5) worst-case turn count ≤ `max_turns`, (6) perturbations sit only at declared
  valid points.
- **Drift guard:** the graph file records sha256 of `agentsim/registry.py` and
  `fixtures/paycard.py`; the validator hard-fails on mismatch.

**Read boundary:** `agentsim/registry.py`, `fixtures/paycard.py`,
`agentsim/scenario.py`, `agentsim/assertions.py`, `scenarios/j1_card_switch_stale_options.yaml`,
`scenarios/j1_happy_path.yaml`.

**Done when:** validator accepts hand-written blueprints reproducing the 5 existing J1
scenarios' semantics, and rejects ≥6 constructed invalid cases (bad tool, unsatisfiable
binding, orphan policy, turn overflow, misplaced perturbation, drift).

---

## Phase 2 — Enumeration, dedup, stratified sampling (still no LLM)

**Goal:** Generate every valid J1 blueprint, measure the space, and sample
deterministically. This phase contains the plan's one big **decision gate**.

**Build**

- `scenario_synthesis/enumerate.py`: walk the J1 graph × compatible policy sets ×
  fixture bindings × valid perturbation placements; validate each candidate; write
  survivors to `generated_scenarios/blueprints/`.
- **Canonical form for dedup:** `(journey, procedure_path, frozenset(policies),
  ordered perturbation (type, position) pairs, fixture equivalence class)` — two
  bindings are equivalent if they satisfy the same predicate set (e.g. any two
  distinguishable-amount card pairs are one class). One representative per class.
- `scenario_synthesis/sample.py`: seeded stratified sampler (stratify by
  policy × perturbation type); identical seed ⇒ byte-identical output.
  `generated_scenarios/manifest.json` records seed, graph hash, fixture hash,
  generator version, counts.

**Decision gate (record the numbers in the phase notes):**
- If the deduped J1 space is ≤ ~5,000 blueprints: enumeration is the permanent
  strategy; evolution stays cut.
- If it explodes: tighten the equivalence classes or cap perturbation combinations
  before reaching for anything cleverer.

**Read boundary:** Phase 1's `scenario_synthesis/` files plus its test file. Nothing
new from `agentsim/`.

**Done when:** enumeration is deterministic (two runs, byte-equal), every declared J1
edge and policy appears in ≥1 blueprint, and the manifest reproduces a sample from
seed alone.

---

## Phase 3 — LLM realization (blueprint → scenario YAML)

**Goal:** One structured LLM call turns an approved blueprint into a scenario YAML that
the **existing, unmodified** `agentsim/scenario.py` loader accepts.

**Build**

- `scenario_synthesis/realize.py`: prompt carries the blueprint's facts and produces
  only: description, persona name + traits, goal prose, and success-criteria prose
  phrased from supplied facts. Output written to `generated_scenarios/yaml/` only.
- **Persona trait whitelist:** `scenario_synthesis/persona_traits.yaml` — a reviewed
  list of trait dimensions (patience, attention to amounts, disclosure style,
  decisiveness). The LLM picks from it; free-text traits are rejected. This is the
  cheap defense against prose smuggling in behavior-altering facts.
- **Deterministic equivalence check:** every last-four, dollar amount, date, account,
  and tool name extracted from the generated prose must appear in the blueprint;
  any number or identifier not in the blueprint ⇒ reject and retry once, then fail.
- Tests use a stubbed LLM client (repo already has this pattern in offline tests);
  live realization only via an explicit `make`/script entry point.

**Read boundary:** `scenario_synthesis/` from Phases 1–2, `agentsim/scenario.py`,
`agentsim/llm.py`, `agentsim/simulator.py` (Persona), two existing scenario YAMLs as
few-shot references.

**Done when:** stubbed tests show valid realizations load through `load_scenario`
unchanged, and adversarial stub outputs (extra fact, altered amount, off-whitelist
trait) are all rejected.

---

## Phase 4 — Dry-run gate + coverage recording

**Goal:** Run generated candidates against the existing mock via the existing
orchestrator; separate simulator-invalid runs from agent failures; record coverage.
Measurement only — no feedback loop.

**Build**

- `scenario_synthesis/dryrun.py`: runs a candidate through `run_scenario` against the
  deterministic mock. Classify each run: `simulator_invalid` (invented facts,
  premature confirmation, abandoned goal — reuse/extend the judge only via a
  *separate* criterion set; shared judge wording untouched), `agent_fail`,
  `agent_pass`, `error`. Do **not** filter on agent pass/fail.
- Coverage record per run appended to the manifest: procedure edges hit, assertions
  fired, judge criteria triggered, tool-result classes seen.
- Offline tests stub the LLM; live dry-runs only on explicit request (repo invariant).

**Read boundary:** `scenario_synthesis/`, `agentsim/orchestrator.py`,
`agentsim/judge.py`, `agentsim/criteria.py`, `agentsim/report.py` (skim for report
hooks only).

**Done when:** a seeded batch of stubbed dry-runs yields a manifest with per-run
classification + coverage, and simulator-invalid counts are reported separately from
agent failures.

---

## Phase 5 — Second journey (J2): the generalization test

**Goal:** Prove the per-journey marginal cost is low. This phase is also a
**kill criterion**: if authoring the J2 graph + predicates takes longer than
hand-writing the scenarios it would generate, stop and reassess before J3–J5.

**Build**

- `scenario_synthesis/procedures/j2.yaml` + J2 fixture predicates (external-account
  warning path, funding-account selection) + policies `external_account_warning`,
  `warning_path` as perturbation.
- Re-run enumeration + realization + dry-run for J2. No framework changes expected;
  if the framework needs changes, that is the finding — record it.

**Read boundary:** `scenario_synthesis/`, `agentsim/registry.py` (J2 tools),
`scenarios/j2_*.yaml`, `agentsim/adapters/mock_paycard/j2_autopay_setup.py` (signatures
only, for tool-result classes).

**Done when:** J2 candidates generate end-to-end, and the phase notes record hours
spent vs. estimated hand-authoring cost. J3/J4/J5 then become three copies of this
phase (one session each), only if the gate passes.

---

## Phase 6 — Promotion path

**Goal:** An explicit, human-gated route from `generated_scenarios/` into `scenarios/`.

**Build**

- `scripts/promote_scenario.py`: takes a candidate ID, re-validates blueprint + YAML
  equivalence + provenance completeness, copies into `scenarios/` with a provenance
  comment header. Never runs automatically.
- A one-page review checklist in `plans/`.
- A comparison report: coverage of the curated 13 vs. a promoted-candidate set
  (edges/policies/assertions exercised), so promotion decisions are evidence-based.

**Read boundary:** `scenario_synthesis/`, `generated_scenarios/`, `scenarios/`
(listing + one file).

**Done when:** one candidate is promoted end-to-end through the command and the
comparison report identifies at least the coverage the curated library lacks.

---

## Phase order and session budget

| Phase | Session | LLM at runtime | Gate |
|---|---|---|---|
| 1 Schema + graph + validator | 1 | No | — |
| 2 Enumerate + dedup + sample | 1 | No | Space size ⇒ enumeration confirmed |
| 3 Realization | 1 | Stubbed in tests | Equivalence check holds adversarially |
| 4 Dry-run + coverage | 1 | Stubbed in tests | Sim-invalid measured separately |
| 5 J2 generalization | 1 | As Phase 3–4 | Kill criterion: authoring cost |
| 5b–5d J3, J4, J5 | 1 each | As above | Only after Phase 5 gate |
| 6 Promotion | 1 | No | Human review only |

Useful scenarios can exist after Phase 3; Phases 5b–5d and 6 are optional until the
J1+J2 output proves worth promoting.
