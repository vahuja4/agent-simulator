# Break the agent — handoff for a fresh session

Rewritten 2026-09-25, replacing the handoff written earlier the same day. That
one described a probe whose customer improvised inside the conversation; the
user rejected that design and it no longer exists. Read this, then ADR 0008
(`docs/adrs/0008-probe-by-climbing-a-per-rule-difficulty-ladder.md`) and
`docs/solutions/probe-rungs-are-ordinary-synthesized-scenarios.md`.
`docs/plans/break-the-agent.md` is the original plan and is now **partly
superseded** — its steps 2 and 6 describe the in-conversation loop. Its
reasoning about fairness, evidence and cost still holds.

Work in `/Users/vishal/Desktop/agent_simulator-langgraph`, branch
`codex/langgraph-synthesis-harness`. Read `AGENTS.md` and `CONTEXT.md` and
follow them. Never touch `main` or `/Users/vishal/Desktop/agent_simulator`.

**A note on language.** `docs/plans/break-the-agent.md` is written in plain
English on purpose. Anything written *into the repo proper* uses the house
vocabulary as normal.

## Where things stand

- Offline tests: **1031 passing**, `ENVIRONMENT.md` holds that number and
  `make test` fails on any drift. Run it before you change code, and never edit
  a tracked file while it is running.
- Five commits on top of `9b53966`, all pushed to the branch:
  `3bf7e44` ADR 0008 and the Openings finder, `38d2861` the Ladder and its four
  Rungs, `4d6cf1f` the climb decision, `3dceb3e` the compound record, `b80d293`
  the Anthropic client.
- **No live model call has been made.** Everything below was built and proven
  offline.

## The design, in one paragraph

Difficulty escalates *between* Episodes, not inside one. A Ladder is an ordered
series of Rungs against one required rule; Rung 1 arranges the Fixture state
condition under which that rule binds and each later Rung stacks one more
Persona or Complication difficulty on the one below. Every Rung is an ordinary
Episode; code reads the saved Verdicts and decides whether to climb. This is
why none of the old plan's landmines apply: no new Termination reason, no edit
to `episode.py` or `evaluation.py`, and `SIMULATED_USER_STOP_REASONS` is
untouched.

## What exists

- `agentsim/journey/probe.py` — Openings, derived from `journey.yaml` +
  `fixture_state.yaml` with no model. Six for the dental Journey; a test pins
  them, so a Fixture edit that moves where a Probe can aim fails loudly.
- `scenario_synthesis/ladder.py` — the `Ladder`/`RungSpec` types, the Rung
  difficulty directions, `realize_ladder` (writes an ordinary synthesized set),
  and `IDENTIFY_EXISTING_APPOINTMENT`, the four Rungs against rule 1.
- `agentsim/journey/climb.py` — the climb decision, with `play` injected.
- `agentsim/anthropic_llm.py` — `AnthropicLLM`, so the Simulated user can leave
  the Judge's family. `anthropic` is an approved dependency exception.

## Decisions already made — don't reopen these

- **The self-marking mechanism is gone.** The 2026-09-21 decision in
  `docs/solutions/journey-simulated-user-fidelity-is-a-human-record.md` stands
  unchanged. A Rung is reviewed by a human before it is played, which is where
  the judgement about fairness now happens. ADR 0008 records this.
- **A Rung realizes an ordinary Synthesized Journey Scenario.** Not a new file
  type, not a widened `origin`. Chosen by the user over both alternatives.
- **ADR 0005's one-Complication rule is untouched.** It keeps Coverage cells
  finite; it was never a limit on how difficult a Simulated user may be. A Rung
  carries several and is never a Coverage cell.
- **Rungs never reuse or edit `_COMPLICATION_DIRECTION`.** Those directions
  resolve their own difficulty and describe the measuring mode's customer.
- **Customer model: `claude-opus-5`. Judge: `gpt-5.5` (calibration-locked).
  Generator: `gpt-5.5`. One Seed per Rung to begin with.** The user chose all
  four on 2026-09-25.
- **No stub rehearsal.** A climb has no stopping logic of its own to prove, and
  a scripted agent answers every Rung the same way.

## What to do next

1. **Generate the four Rungs.** First spend: four calls to `gpt-5.5`.
   `realize_ladder(IDENTIFY_EXISTING_APPOINTMENT, "journeys/appointment_rescheduling",
   provider=LiveNarrativeProvider.from_model("gpt-5.5"))`. It writes
   `synthesized_journey_scenarios/appointment-rescheduling/ladder-identify-existing-appointment/`.
   **Show the four Scenarios to the user before anything is played** — that
   human read is what ADR 0008 puts in place of the self-check.
2. **Climb rule 1 against the LangGraph agent.** Nothing yet wires `climb`'s
   `play` to `run_episode` + `evaluate_episode`; that is the one piece of
   plumbing still missing, and `scripts/journey_harness.py:run_command` is the
   shape to copy (it already injects adapter, Simulated user and Judge).
3. **The user's Persona-fidelity spot-check** of the Opus customer. `AGENTS.md`
   requires it before reported use, and it is a human read — not yours to do.
   Records go under `journey_spot_checks/`.
4. Then: a Spot-check-style record for a ruling on one suspected finding
   (original plan step 3), and the design note (step 4).

## Landmines — each of these cost this session time

- **Do not claim a guard is missing from a document's wording.** This session
  reported that a Simulated user could quote a Fixture id; two guards already
  existed and a test already pinned one. `AGENTS.md` now carries the rule.
- **Measure the baseline, do not predict it.** Writing a guessed pass count
  into `ENVIRONMENT.md` fails `make test`. Run the suite, read the number,
  then write it.
- **A constrained lockfile recompile.** `uv pip compile -c requirements.lock`,
  or an approved single dependency also drags `openai` and six transitive pins.
- **`model_family` grouped only GPT models** until this session; every
  Anthropic model is now one family. An unrecognized id is still its own, which
  fails closed.
- **The offline narrative stub cannot realize a Rung** — it reads the measuring
  mode's single `complication_direction`. Use `StubLadderNarrativeProvider`.
- **Rungs 3 and 4 share two directions.** A test that finds a Rung by matching
  its prose will silently select the wrong one. Resolve a Rung by its number.
- **Realizing a Ladder aborts on a Rung that cannot be realized**, rather than
  leaving a gap. A Ladder missing Rung 2 is not a shorter Ladder.

## Still open

- **Seeds.** One for now. A single Seed cannot say whether a break is reliable,
  which is the number a reviewer wants; revisit once a climb has run.
- **`task_incomplete` counts as survived.** Rung 3 is built to end that way. If
  the user ever wants an unfinished conversation to count against the agent,
  it is one line in `climb.py` — but it would make Rung 3 unpassable.
- **Ladders for the other four rules.** Only `identify_existing_appointment`
  exists. Its Assertion is the one realistically reachable; the others fall to
  the Judge and cost a human read per Rung.
- **Rung order is a guess.** Whether a false premise is harder than time
  pressure is not known; it should be learned from results rather than decreed.
- **Nothing checks `permitted_behavior`.** Moving a completed appointment (Priya's
  A-3002) breaks no required rule, so the Openings finder does not report it.

## Housekeeping

- The ignored `.env` is in both repositories. Export with
  `set -a; . ./.env; set +a`; never print a key. Both `OPENAI_API_KEY` and
  `ANTHROPIC_API_KEY` are needed now.
- **No live model calls** without the user explicitly asking.
- This is a git worktree sharing a stash stack. Never use bare `git stash`.
- Run the `compound` skill before ending a session that implemented, debugged
  or reviewed anything, and commit its outputs.
