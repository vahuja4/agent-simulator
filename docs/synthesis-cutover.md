# Delete at cutover

- `scenario_synthesis/enumerate.py`
- `scenario_synthesis/sample.py`
- `scenario_synthesis/compatibility.py`
- `scenario_synthesis/dryrun.py`
- `scripts/realize_scenarios.py`
- `scripts/dryrun_scenarios.py`
- `scenario_synthesis.blueprint.Blueprint`
- `scenario_synthesis.validator.BlueprintValidator`

# Cutover test

Run both pipelines on the same contracts, diff the resulting scenario YAML, and expect identical sets.

# 4.5 still needs

- `generator.generate_blueprints`: no production callers; tests only.
- `blueprint.dump_coverage_blueprint`: no callers.
- `realize.realize_blueprint`: no production callers; tests only.

Connect them to `realize.realize_catalog` by adding Phase 4.5 `CoverageBlueprint` support or an adapter, then making the CLI call `generate_blueprints`, persist each blueprint with `dump_coverage_blueprint`, and pass the generated catalog to `realize_catalog`.
