---
title: Explicit live scenario-synthesis wiring
category: scenario-synthesis
symptoms:
  - Produce and Qualification had only offline stub providers.
  - The legacy live smoke test bypassed Qualification evidence retention.
---

# Explicit live scenario-synthesis wiring

## Question

How should `produce --live` and `qualify --live` reach real models, and should the
pre-Phase-2 live smoke test remain as a separate live path?

## Decision

`python -m scenario_synthesis produce --live --cell-id <cell-id>` realizes one
reviewed Blueprint with the simulator model pinned in `scenario_synthesis/config.yaml`.
`python -m scenario_synthesis qualify --live --candidate-id <candidate-id>` runs the
required defects-off and, where applicable, defect-on repetitions through the existing
`run_scenario` and Judge machinery. The deterministic mock configuration is verified
before each Episode. The configured simulator is `gpt-5.6-luna`; the calibrated Judge
remains `gpt-5.5`. No Judge prompt or criterion wording changed.

Both commands require the explicit `--live` flag before constructing live providers.
`--stub` remains the explicit offline development mode, and ordinary tests construct
no live client.

The pre-Phase-2 `tests/test_live_smoke.py` test is superseded and removed. Its useful
coverage—one real simulator conversation plus the existing Judge against the faithful
mock—is a strict subset of `qualify --live`: Qualification runs three defects-off
repetitions, adds targeted defect-on repetitions when required, enforces distinct
configured simulator and Judge models, and retains hashed trace, Transcript, Assertion,
Judge, and simulator-compliance evidence. Keeping the old smoke entry point would create
a second live path without Qualification's durable evidence contract.

## Why

One command surface keeps live authorization, configured model identity, retry and
repetition bounds, mock configuration, admission evaluation, and evidence retention
under the Phase 4.5 contract. Qualification is a strict superset of the smoke test and
uses the existing `run_scenario` and Judge machinery without changing Judge prompts or
criteria.

## What would make us revisit it

Revisit if the persisted live-run bundle contract moves out of Qualification. Any
replacement must still require explicit live authorization.

Task 5a changed wiring and offline tests only. It did not execute any live call.
