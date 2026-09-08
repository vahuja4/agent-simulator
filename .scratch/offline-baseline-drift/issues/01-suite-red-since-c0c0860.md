# Offline suite has been red since c0c0860; ENVIRONMENT.md baseline is stale

Status: open
Type: task

## Problem

On `main` at `74609b4` the offline suite is **17 failed / 435 passed**.
`ENVIRONMENT.md` still records `451 passed`. The drift entered with `c0c0860`
("switch simulator to gpt-5.6; …") and was not caught because nothing compared
the suite result to the recorded baseline. `scripts/check_offline_baseline.py`
(run by `make test`) now fails on any drift, so this issue is what makes it green
again.

## The 17 failures, by cause

1. **14 tests** — `ScenarioError: generated_j1_amount_correction.yaml: synthesized
   Scenario cannot load as curated`. Two synthesized Scenarios
   (`generated_j1_amount_correction.yaml`, `generated_j1_false_premise.yaml`) are
   committed under `scenarios/`, which `load_library` treats as curated. Affects
   `test_scenario.py::test_starter_library_loads_cleanly`, all of
   `test_phase4_acceptance.py`, and `test_live_calibration_infrastructure.py`.
   Decide: move them to the synthesized library, delete them, or teach the
   curated loader to skip them.
2. `test_live_providers_pin_current_configured_models_without_calling_them` —
   asserts `gpt-5.6-luna`; `scenario_synthesis/config.yaml` now says `gpt-5.6`.
   Update the test to read the configured value, or pin the model deliberately.
3. `test_admitted_ordinal_one_bundle_validates_its_snapshot_criterion_set` —
   validates a committed `synthesized_scenarios/` bundle against current contract
   hashes; `c0c0860` changed `pair-exclusions.yaml` and
   `persona-archetypes.yaml`, so `qualification evidence identity or
   configuration mismatch`. Either the bundle needs re-qualifying under the new
   contracts or the test should pin the bundle's own hashes.
4. `test_check_completion_fails_honestly_without_resolved_graph_gaps` — clause
   expectations moved with the same contract change.

## Done when

`make test` prints `baseline check: OK` on `main`, and `ENVIRONMENT.md` records
the new green count in the same commit.
