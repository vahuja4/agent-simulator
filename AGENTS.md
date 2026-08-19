# Agent rules for this repository

<!-- Canonical: CLAUDE.md imports this file. -->

## Environment

- Use `.venv/bin/python` exclusively. Never use Conda or system Python.
  The Miniconda base interpreter has a corrupted native `readline`; see
  `ENVIRONMENT.md`.
- Before running Python, verify that `.venv/bin/python --version` reports
  Python 3.12.12 and `.venv/bin/python -c "import readline"` succeeds.
- If `.venv` is missing or fails either check, run `make setup`. If setup
  is unavailable or fails, stop and report the problem—do not fall back
  to another interpreter.
- Run tests with `.venv/bin/python -m pytest`. Tests are offline by
  default; live tests are marked and deselected.
- The expected baseline is recorded in `ENVIRONMENT.md`. Verify it before
  code changes unless the current prompt imposes a narrower read boundary.

## Project invariants

Do not violate these without explicit instruction in the current prompt.

- The mock under `agentsim/adapters/mock_paycard/` is deterministic and
  makes no LLM calls. Mock behavior changes require explicit approval.
- Do not change judge criterion wording unless explicitly approved. Any
  approved wording change must be live-verified before its phase closes.
- `agentsim_generic_refactoring_plan.md` is deferred. Do not implement it.
- Run live LLM calibration or acceptance only when explicitly requested,
  never as a side effect of tests or other commands.
- Do not silently mutate committed scenario YAML files. Persona variation
  uses overlay files.
- Simulator and judge must be from different model families for any reported
  run (acceptance-gate runs and Phase 5 live runs). Development runs against
  the mock may share a model. Separation will be achieved by changing the
  simulator family while keeping the calibrated judge model fixed, and the
  new simulator model requires a persona-fidelity spot-check before reported
  use. The model-family enforcement flag is default-off during development
  and becomes mandatory-on at Phase 5.

## Hygiene

- Preserve existing user changes.
- Leave Git clean. Commit evidence artifacts rather than leaving them
  untracked unless the current prompt explicitly requires otherwise.
- Honor all prompt-imposed file-reading and evidence boundaries.
  Otherwise inspect only files relevant to the task; do not browse old
  calibration transcripts, build plans, or unrelated artifacts.
