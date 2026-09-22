# Journey harness — setup and run

How to set up, start the agent service, and run the three commands of the
Journey harness (`synthesize` → `run` → `summarize`) against the LangGraph
appointment-rescheduling agent. Written in session 09 (2026-09-22) against
what the commands do now; `--help` on each command is the reference when the
two disagree. The contract is `docs/plans/langgraph-harness.md`.

**As written (session 09), nothing on this path had run against a real
model**: every command below that makes a model call had been exercised only
on doubles in the test suite, and the one thing that had run for real was the
transport: the harness adapter against AGENT's **stub** service (see "Contract
re-check"). Since then, one **development Run** has been performed, on
2026-09-22 (session 10), at the user's explicit request:
`docs/reports/live-runs/live-dev-01/README.md` records it, its findings, and
why it is not reportable (Simulated user and Judge in the same model family).
The rest of this document is unchanged and still describes the commands; the
"Configuration a live Run needs" table below records what that Run configured.

## The two repositories

| Name | Path | Branch |
|---|---|---|
| HARNESS (this repository) | `/Users/vishal/Desktop/agent_simulator-langgraph` | `codex/langgraph-synthesis-harness` |
| AGENT | `/Users/vishal/Desktop/journey_agent` | `codex/langgraph-synthesis-harness` |

The harness never imports AGENT or LangGraph; it talks to the agent service
over HTTP on `127.0.0.1` only, through `agentsim/adapters/journey_service.py`.

## Setup

Each repository has its own `.venv` on Python 3.12.12 (never Conda or system
Python — see `ENVIRONMENT.md`).

    # HARNESS
    make setup      # .venv from requirements.lock, then make doctor
    make test       # offline; expected: the baseline in ENVIRONMENT.md

    # AGENT
    make setup
    make test       # offline; the LangGraph agent runs on model doubles

## Start the agent service

In AGENT (its `README.md` has the full operation and model tables):

    .venv/bin/python -m journey_agent.service --port 8765 --agent stub        # scripted, no model
    .venv/bin/python -m journey_agent.service --port 8765 --agent langgraph   # the LangGraph agent

`make serve AGENT=stub` and `make serve` (LangGraph) are the same two. The
LangGraph agent needs `JOURNEY_AGENT_MODEL` (`provider:model`, provider
`openai` or `anthropic`) and that provider's API key in the service's
environment; it exits with one line before anything listens when they are
missing. Export AGENT's ignored `.env` into that shell first
(`set -a; . ./.env; set +a`).

## One end-to-end invocation

From HARNESS, with the service listening on `http://127.0.0.1:8765`. `<dir>`
is any directory outside `scenarios/`, `synthesized_scenarios/` and
`generated_scenarios/`; the defaults are `synthesized_journey_scenarios/` and
`journey_runs/`.

**1. Synthesize** four Scenarios from the Journey definition and Fixture
state. `--stub` writes deterministic placeholder narrative and makes no model
call; without it, set `AGENTSIM_SYNTHESIS_MODEL` (or `--model`) and
`OPENAI_API_KEY`.

    .venv/bin/python scripts/journey_harness.py synthesize \
        --journey journeys/appointment_rescheduling --count 4 --set-id demo --stub \
        --output-root <dir>/sets

Writes `<dir>/sets/appointment-rescheduling/demo/{provenance.json, accepted/*.yaml, rejected/*.json}`.
Exit 0; 1 on a shortfall or when the run aborted after writing (one
`ABORTED:` line; what was written is kept and `provenance.json` says
`status: aborted`); 2 for an unusable request, before any write. Validation is
not Qualification: passing it says nothing about test quality or coverage.

**2. Run** one Episode per accepted Scenario, one after another, and evaluate
each as soon as it is saved. **Makes live model calls** (the Simulated user
and the Judge) — needs `AGENTSIM_SIMULATOR_MODEL` (or `--simulator-model`) and
`OPENAI_API_KEY`; refuses with one line before any write when they are missing.

    .venv/bin/python scripts/journey_harness.py run \
        --journey journeys/appointment_rescheduling \
        --scenarios <dir>/sets/appointment-rescheduling/demo \
        --service-url http://127.0.0.1:8765 --run-id demo-run \
        --output-root <dir>/journey_runs

Before writing anything, `run` checks the set's provenance against
`--journey` (the Scenarios must have been synthesized from that exact
`journey.yaml` and `fixture_state.yaml`), refuses an existing Run directory,
and **opens and releases one probe conversation** to learn whether the stub or
the LangGraph agent is answering; it prints `agent: stub` or
`agent: langgraph` before the first Episode, and the Run record keeps it. A
Run against the stub is a transport check, not a result.

Writes `<dir>/journey_runs/demo-run/`:

| File | What |
|---|---|
| `journey_run.json` | the Run record: `status` `running` → `complete` or `aborted`, inputs and their hashes, agent kind, models, timeouts, `error`, and `re_evaluation` (below) |
| `manifest.json` | `BatchRunner`'s per-Episode records — the only thing clustering reads |
| `runs/<run_key>/` | one directory per Episode: `scenario.yaml`, `transcript.jsonl`, `episode.json`, `raw_trace.json`, `normalized_trace.json`, `evaluation.json`, plus `BatchRunner`'s `trace.json`, `transcript.md`, `run.json` |

Exit 0 when the Run finished, whatever the outcomes — a `fail` or an `error`
Episode is a result, not a command failure; 1 when it aborted after the first
write (an interrupt, a failed write: `journey_run.json` says `aborted` with
the error, every completed Episode is kept); 2 for an unusable request.
Options: `--request-timeout` (per request to the service, default 120 s),
`--episode-timeout` (per Episode, checked between Turns, default 600 s),
`--enforce-model-family-separation` (see below).

**3. Summarize** the Run: cluster its failures and write the report.

    .venv/bin/python scripts/journey_harness.py summarize <dir>/journey_runs/demo-run

Writes `clusters.json` and `report.md` into the Run directory and prints the
outcome counts. Clusters are similar failure symptoms, not proven common root
causes. When the Run was aborted the summary and the report say so and cover
only what ran.

### Re-evaluating a saved Run

    .venv/bin/python scripts/journey_harness.py run \
        --journey journeys/appointment_rescheduling --re-evaluate <dir>/journey_runs/demo-run

Evaluates the saved Episodes again (Assertions, then the Judge — a live Judge
call per Episode) and replays no conversation: `evaluation.json` and the
manifest records are replaced, conversation files are untouched. It refuses a
Journey directory edited since the Scenarios were written, because criterion
wording lives in `journey.yaml`. Whether the conversations finished
(`journey_run.json` `status`) and whether the last re-evaluation finished
(`re_evaluation: {status, started_at, ended_at, error}`) are recorded apart:
an interrupted re-evaluation leaves the Run's own status alone, and
`summarize` names it separately ("the last re-evaluation was ABORTED") — run
`--re-evaluate` again.

### Spot-check records

`journey_runs/` is git-ignored (a development Run is not evidence);
`journey_spot_checks/` is **not** — those human records of Simulated-user
fidelity are the evidence a reported Run needs (format in
`agentsim/journey/spot_check.py`). Consequence: a Spot-check record validates
only on a machine that still has the Run it points to. Validate one with

    .venv/bin/python -m agentsim.journey.spot_check <file> [--runs-root journey_runs]

which does nothing else (exit 0, or 2 with one line).

## The committed offline walkthrough

`run` deliberately has no doubles mode outside pytest: a committed "pass"
from a Judge double would read as a result. So the walkthrough evidence is:

- **Synthesis, for real, on the stub provider:**
  `synthesized_journey_scenarios/appointment-rescheduling/stub-walkthrough/`
  is the output of step 1 with `--set-id stub-walkthrough` and the default
  output root: four accepted Scenarios, zero rejected attempts, and a
  `provenance.json` stamped `model: stub`. It is labelled stub-generated in
  `synthesized_journey_scenarios/README.md`; its narrative text is
  placeholder, not model output.
- **synthesize → run → evaluate → summarize, on doubles, inside the test
  suite:** `tests/test_journey_e2e.py::test_synthesize_run_summarize_offline`
  (session 08) synthesizes a stub set, `run`s it over real HTTP through the
  real `JourneyServiceAdapter` and normalizer against a fake agent service in
  the test process, with a Simulated-user double and a Judge double, then
  `summarize`s the Run. `tests/journey_run_doubles.py::play_run` plays a whole
  Run on doubles for any other test. It shows the pieces fit and leave every
  file they promise. Nothing from those runs is committed as a result, and
  none of it says anything about Judge accuracy, the agent, or the Scenarios.

## Contract re-check (do this whenever AGENT's service changes)

The two raw Traces pinned in `tests/fixtures/journey_agent_raw_traces/`
(`successful.json`, `tool_failure.json`; captured from AGENT's stub in session
05a) catch drift from the HARNESS side only: if AGENT's raw Trace format
changes, nothing in this repository fails. Re-capture and compare:

    # AGENT, in its own shell
    .venv/bin/python -m journey_agent.service --port 8765 --agent stub

    # HARNESS
    .venv/bin/python scripts/recapture_journey_agent_traces.py \
        --fixture-state /Users/vishal/Desktop/journey_agent/tests/fixtures/fixture_state.json \
        --service-url http://127.0.0.1:8765 --output-dir <dir>/recaptured

The script plays the same three customer messages as the samples, once
without and once with the controlled `update_appointment` failure, against
AGENT's own test Fixture state (the one the samples' `fixture_state_sha256`
names), through the harness adapter, and compares each raw Trace with its
pinned sample with `conversation_id` set aside (the raw Trace holds no
timestamp). Exit 0: same. Exit 1: they differ — stop and report; do not update
either side to make them agree. Last run 2026-09-22 (session 09) against AGENT
`ee72c7f`: both the same.

## Configuration a live Run needs

"State" is what the development Run `live-dev-01` (2026-09-22) did; a
reported Run is still blocked by the last two rows.

| What | Setting | State |
|---|---|---|
| Harness credentials | `OPENAI_API_KEY` in HARNESS's ignored `.env`, exported into the shell (`set -a; . ./.env; set +a`); never printed | done for `live-dev-01` (the `.env` copied from ORIGINAL; Git worktrees do not share it) |
| Synthesis generator | `AGENTSIM_SYNTHESIS_MODEL` or `--model` (not needed with `--stub`) | `--model gpt-5.5` in `live-dev-01` |
| Simulated user | `AGENTSIM_SIMULATOR_MODEL` or `--simulator-model`, required | `--simulator-model gpt-5.5` in `live-dev-01` (same family as the Judge: development only) |
| Judge | the constant `gpt-5.5` in `agentsim/journey/judge.py`; no flag or variable moves it (`AGENTSIM_MODEL` included) | fixed |
| LangGraph agent | `JOURNEY_AGENT_MODEL` (`provider:model`) plus `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in AGENT's environment | `anthropic:claude-sonnet-5` in `live-dev-01`; the harness records the agent kind, not its model |
| Model-family separation | `run --enforce-model-family-separation` (default off) refuses a Simulated-user model of the Judge's family. A **reported** Run requires it on, and a Simulated-user model outside the `gpt-5` family — which the single shared OpenAI client in `agentsim/llm.py` cannot reach today, so a reported Run is blocked; development Runs work | blocked |
| Persona-fidelity spot-check | required before any reported use of a Simulated-user model or of these instructions (`AGENTS.md`); recorded as Spot-check records | no record exists |

A first live Run, when explicitly requested, is a development Run: export the
keys, start the LangGraph agent, synthesize three to five Scenarios without
`--stub`, `run`, `summarize`, and read the conversations. Things to watch, and
what `live-dev-01` (four Episodes, one measurement each) showed: whether 120 s
per request holds — longest request ≤ 6.6 s, longest Episode 51.7 s; how often
the lexical Sealed-world check rejects honest narrative — 0 of 4 attempts;
whether any Episode is `error` from `agent_error` (the agent's 16-step limit)
— none, 4 to 8 customer Turns each; whether a high-Knowledge-level customer
restates its rule more often than a person would — both stated it once.

## What offline tests do not establish

Judge accuracy, Simulated-user fidelity, Sierra readiness, test quality,
coverage, Qualification or Admission. The `JourneyJudge` criteria are new and
uncalibrated; every prompt on this path is designed, not validated.
`docs/reports/judge-and-simulated-user-reliability.md` is the research on
what measuring them would take.
