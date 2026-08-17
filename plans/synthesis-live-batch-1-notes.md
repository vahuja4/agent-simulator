# Scenario synthesis live batch 1 notes

Date: 2026-08-17

The Step 2 dry-run command was invoked exactly once. It completed with exit code 0 and persisted 27 candidate records, each containing one faithful run and one targeted-defect run.

## Results

- Solvable rate: **0/27 (0%)** faithful runs classified as `agent_pass`.
- `simulator_invalid`: **0**. There are no compliance-judge reasons to report because simulator compliance was `not_evaluated` for every run.
- Defect-sensitive rate among targeted runs: **0/27 (0%)** recorded as defect-sensitive.
- Error count: **54 run errors across 27 candidates** (27 faithful and 27 targeted-defect runs). Every run recorded `run_scenario raised APIConnectionError: Connection error.`

The solvable and defect-sensitive rates are recorded outcomes, not meaningful candidate-quality estimates: all runs failed before scenario execution and compliance judging, so no candidate received behavioral evidence.

## Three most suspicious candidates

All 27 candidates are tied because they have the same pre-execution connection error and empty coverage. The first three in manifest order are listed as deterministic representatives of that tie:

- `j1-6fd3cce8c9eff872` — both configurations errored before execution, leaving no solvability, compliance, defect-detection, or coverage evidence.
- `j1-1a8cef237cb9a615` — both configurations errored before execution, leaving no solvability, compliance, defect-detection, or coverage evidence.
- `j1-82b14c01dcd19612` — both configurations errored before execution, leaving no solvability, compliance, defect-detection, or coverage evidence.

No candidates were deleted, edited, or rerun after the single batch invocation.
