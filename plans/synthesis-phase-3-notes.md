# Scenario Synthesis Phase 3 Notes

**Date:** 2026-08-17
**Scope:** Phase 3 only; no dry-run, coverage recording, calibration, or Phase 4 work.

## Decisions

- The 3,748-blueprint audit catalog remains intact. Before sampling or realization,
  blueprints are grouped by journey, procedure path, ordered perturbations, and
  exact fixture bindings. Policy labels are excluded from this behavioral key.
- The maximal-policy representative of each class is selected deterministically
  (policy count, policy tuple, then blueprint ID as tie-breakers). This produces
  **353 behavioral classes**, matching the Phase 2 review amendment.
- Sampling strata are computed only over those 353 representatives. Seed 0 with
  one selection per observed stratum now yields **27 sampled behavioral classes**.
- The reviewed persona whitelist has four required dimensions: patience, attention
  to amounts, disclosure style, and decisiveness. Structured output must choose
  exactly one listed value for every dimension; free-text or omitted traits fail.
- Deterministic prose validation rejects numeric identifiers, dollar amounts,
  numeric dates, or registry tool names absent from the serialized blueprint. A
  rejected model output is retried exactly once and then fails closed.
- Realization preserves all deterministic scenario fields from the blueprint and
  lets the model supply only description, persona name and whitelisted traits,
  goal prose, and success-criteria prose.
- Production writes are fixed to `generated_scenarios/yaml/`. Live realization is
  available only through the explicit command
  `.venv/bin/python -m scripts.realize_scenarios`; it was not run in this phase.
- Each live-realization manifest entry records `scenario_id`, `blueprint_id`, and
  `behavioral_class_key`. The deterministic manifest initializes the entry list as
  empty because no live realization was requested.

## Done-when evidence

- A valid stubbed realization loads through the existing, unchanged
  `agentsim/scenario.py::load_scenario` loader.
- Adversarial stub outputs containing an extra last-four, an altered dollar amount,
  and an off-whitelist trait are rejected after exactly one retry.
- A reject-then-correct stub succeeds on the single permitted retry.
- A batch containing two policy labelings of one behavior makes one stubbed LLM
  call, realizes the maximal-policy representative, and records its behavioral key.
- Full offline suite: **279 passed, 1 deselected** via
  `.venv/bin/python -m pytest` on Python 3.12.12.
- Live LLM calls: **none**.
- Phase 4: **not started**.
