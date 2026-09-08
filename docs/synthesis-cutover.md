# Deleted 2026-09-08

These had no production callers. The Phase 4.5 CLI realizes blueprints through
`scenario_synthesis.realization_provider` and never touched them.

- `scenario_synthesis/realize.py`
- `scenario_synthesis/dryrun.py`
- `scripts/realize_scenarios.py`
- `scripts/dryrun_scenarios.py`
- `tests/test_scenario_synthesis_phase3.py`, `tests/test_scenario_synthesis_phase4.py`

# Still to delete at cutover

- `scenario_synthesis/compatibility.py`
- `scenario_synthesis/enumerate.py`
- `scenario_synthesis/sample.py`
- `scenario_synthesis.blueprint.Blueprint`
- `scenario_synthesis.validator.BlueprintValidator`

# What blocks the rest

`planner.py` imports `compatibility.prototype_unemittable_pairs` and
`compatibility.read_historical_quarantine` to build the
`prototype_eligibility_reconciliation` section of `coverage.json`, which the
completion evaluator accepts as evidence while its contract hashes stay current.
`compatibility.py` in turn enumerates legacy blueprints through `enumerate.py`,
`sample.py`, the legacy `Blueprint` class, and `BlueprintValidator`.

The remaining modules can go once that reconciliation is either frozen as a
committed, hashed artifact or dropped from the planner.
