# Agent rules for this repository

<!-- Canonical: CLAUDE.md imports this file. -->

Read `CONTEXT.md` and use its vocabulary exactly — in code identifiers,
filenames, and prose.

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
- The expected baseline is recorded in `ENVIRONMENT.md`. Run the full baseline
  test suite and verify its result before code changes unless the current prompt
  imposes a narrower read boundary.

## Project invariants

Do not violate these without explicit instruction in the current prompt.

- Zero new dependencies: use the stdlib plus what is already in the
  environment. If a task appears to need a new package, stop and ask.
- All agent-platform access goes through the agent adapter interface. No
  platform client code may be imported elsewhere.
- The mock under `agentsim/adapters/mock_paycard/` is deterministic and
  makes no LLM calls. Mock behavior changes require explicit approval.
- Do not change judge criterion wording unless explicitly approved. Any
  approved wording change must be live-verified before its phase closes.
- The calibration-locked judge model is `gpt-5.5`; see `calibration_runs/step3/REPORT.md` ("Live verification (model gpt-5.5)").
- `agentsim_generic_refactoring_plan.md` is deferred. Do not implement it.
- Run live LLM calibration or acceptance only when explicitly requested,
  never as a side effect of tests or other commands.
- Do not silently mutate committed scenario YAML files. Persona variation
  uses overlay files.
- Validate contract preconditions against their governing ADR definitions,
  never against a single curated exemplar.
- Before any simulator-instruction change lands, check it for conflicts with
  existing scenario Personas.
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
- If preserving existing user changes conflicts with leaving Git clean, stop
  and surface the dirty state to the user. Never silently build around it.
- Honor all prompt-imposed file-reading and evidence boundaries.
  Otherwise inspect only files relevant to the task; do not browse old
  calibration transcripts, build plans, or unrelated artifacts.

## Agent skills

After completing any implement, debugging, or review task, run the compound skill before ending the session.
Compound must record review findings from the current and carried-over sessions; do not omit a finding merely because its code correction was already committed.

### Issue tracker

Issues are tracked as local Markdown files under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Domain docs

Domain documentation uses a single-context layout. See `docs/agents/domain.md`.

## Delegation and sub-agents

The primary agent may delegate bounded tasks to sub-agents when doing so
improves context isolation or enables independent work.

- Each delegated task must have a narrow goal and explicit acceptance criteria.
- Sub-agents inherit all rules and invariants in this file.
- Sub-agents must respect any file-reading or evidence boundaries imposed by
  the parent prompt.
- Prefer investigation-only sub-agents for exploratory work; they should not
  modify files unless explicitly authorized.
- Do not delegate architectural decisions that materially affect multiple
  components without returning the decision to the primary agent.
- Avoid multiple agents editing the same files concurrently unless the work is
  intentionally isolated in separate worktrees.
- The primary agent is responsible for reviewing delegated results before
  integration.
- After integrating delegated work, run the relevant combined validation rather
  than relying only on each sub-agent's local test result.
- Return concise findings to the primary agent; do not copy large transcripts,
  logs, or exploratory reasoning into the parent context.
