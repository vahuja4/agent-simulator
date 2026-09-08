---
title: Legacy scenario-synthesis cutover boundary
category: scenario-synthesis
symptoms:
  - Modules tagged LEGACY were assumed removable because no non-legacy docstring named them.
  - docs/synthesis-cutover.md claimed generator and blueprint functions had no callers after they had gained them.
  - Deleting enumerate.py or sample.py would have broken the plan and report commands through compatibility.py.
---

# Legacy scenario-synthesis cutover boundary

## Question

Which pre-Phase-4.5 synthesis modules can be removed now, and what keeps the
rest alive?

## Decision

Removed on 2026-09-08: `scenario_synthesis/realize.py`,
`scenario_synthesis/dryrun.py`, `scripts/realize_scenarios.py`,
`scripts/dryrun_scenarios.py`, and the two test files that covered only them.
The Phase 4.5 CLI realizes blueprints through `realization_provider` and never
touched them.

Kept: `enumerate.py`, `sample.py`, `compatibility.py`, the legacy `Blueprint`
class, and `BlueprintValidator`. `planner.py` builds the
`prototype_eligibility_reconciliation` section of `coverage.json` through
`compatibility.py`, and the completion evaluator accepts that section as
evidence while its contract hashes stay current. `compatibility.py` enumerates
legacy blueprints through `enumerate.py`, `sample.py`, and the legacy validator.
The single production edge `planner -> compatibility` is pinned by
`tests/test_synthesis_cutover_boundary.py`; the removed files are asserted absent.

## Why

A LEGACY docstring records intent, not reachability. Transitive importers from
non-legacy code are the only evidence that a module has no production callers,
and the first assessment this session got the boundary wrong by trusting the
tag. The boundary test makes the documented edge the only one that passes, so a
new production dependency on the legacy set fails loudly instead of quietly
widening the cutover.

## What would make us revisit it

The remaining modules can go once the prototype reconciliation is either frozen
as a committed, hashed artifact that `planner.py` reads, or dropped from the
planner by an ADR that replaces clause evidence for eligibility reconciliation.
Either change must update `ALLOWED_PRODUCTION_EDGES` in the boundary test and
`docs/synthesis-cutover.md` in the same commit.
