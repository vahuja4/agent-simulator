# Scenario Synthesis Phase 2 Notes

**Date:** 2026-08-17
**Scope:** Phase 2 only; no realization, dry-run, calibration, or Phase 3 work.

## Decisions

- J1 enumeration walks every terminal path and permits each cyclic edge at most
  once. In particular, `fetch_options → select_card` occurs no more than once per
  blueprint.
- Fixture bindings are deduplicated by the complete set of graph and policy
  predicates they satisfy. The lexicographically first binding is retained as the
  representative of each equivalence class.
- Perturbations retain graph order, cannot share a position, and are capped at two
  per blueprint. This is the decision-gate tightening that prevents the unrestricted
  perturbation power set from dominating the useful space.
- Sampling uses stable SHA-256 ranks over `(seed, stratum, blueprint ID)` rather
  than runtime-dependent random iteration. A blueprint participates in each of its
  policy × perturbation-type strata; `none` represents an empty side.
- All generated candidates are in `generated_scenarios/blueprints/`. The reviewed
  references in `scenario_synthesis/blueprints/` were not modified.

## Decision gate

- Deduped J1 blueprint space: **3,748**.
- Seed: **0**; one selection per observed stratum produced **35** sampled IDs.
- Since 3,748 is below the plan's approximate 5,000-blueprint threshold,
  **deterministic enumeration remains the permanent strategy and evolution stays
  cut**.

### Per-stratum counts

| Policy | Perturbation | Count |
|---|---|---:|
| `card_switch_resets` | `card_switch` | 288 |
| `card_switch_resets` | `none` | 96 |
| `card_switch_resets` | `partial_disclosure` | 528 |
| `card_switch_resets` | `submission_failure` | 768 |
| `card_switch_resets` | `validation_block` | 432 |
| `card_switch_resets` | `validation_retry` | 288 |
| `card_switch_resets` | `validation_warning` | 432 |
| `disambiguate_last_four` | `card_switch` | 192 |
| `disambiguate_last_four` | `none` | 64 |
| `disambiguate_last_four` | `partial_disclosure` | 352 |
| `disambiguate_last_four` | `submission_failure` | 512 |
| `disambiguate_last_four` | `validation_block` | 288 |
| `disambiguate_last_four` | `validation_retry` | 192 |
| `disambiguate_last_four` | `validation_warning` | 288 |
| `explicit_confirmation` | `card_switch` | 288 |
| `explicit_confirmation` | `none` | 104 |
| `explicit_confirmation` | `partial_disclosure` | 568 |
| `explicit_confirmation` | `submission_failure` | 826 |
| `explicit_confirmation` | `validation_block` | 464 |
| `explicit_confirmation` | `validation_retry` | 310 |
| `explicit_confirmation` | `validation_warning` | 464 |
| `none` | `card_switch` | 48 |
| `none` | `none` | 20 |
| `none` | `partial_disclosure` | 108 |
| `none` | `submission_failure` | 157 |
| `none` | `validation_block` | 88 |
| `none` | `validation_retry` | 59 |
| `none` | `validation_warning` | 88 |
| `tool_output_truth` | `card_switch` | 288 |
| `tool_output_truth` | `none` | 104 |
| `tool_output_truth` | `partial_disclosure` | 568 |
| `tool_output_truth` | `submission_failure` | 826 |
| `tool_output_truth` | `validation_block` | 464 |
| `tool_output_truth` | `validation_retry` | 310 |
| `tool_output_truth` | `validation_warning` | 464 |

## Done-when evidence

- Two independent writes with the same seed are byte-identical.
- Every declared J1 graph edge and every catalog policy appears in at least one
  generated blueprint.
- The manifest's sample is reproduced from its seed and `sample_per_stratum` alone.
- Full offline suite: **272 passed, 1 deselected** via
  `.venv/bin/python -m pytest` on Python 3.12.12.
- Live LLM calls: **none**.
- Phase 3: **not started**.
