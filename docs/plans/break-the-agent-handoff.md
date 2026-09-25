# Break the agent — handoff for a fresh session

Updated 2026-09-25 (second session of the day). Read this, then ADR 0008
(`docs/adrs/0008-probe-by-climbing-a-per-rule-difficulty-ladder.md`) and
`docs/solutions/probe-rungs-are-ordinary-synthesized-scenarios.md`.
`docs/plans/break-the-agent.md` is the original plan and is now **partly
superseded** — its steps 2 and 6 describe an in-conversation loop the user
rejected. Its reasoning about fairness, evidence and cost still holds.

Work in `/Users/vishal/Desktop/agent_simulator-langgraph`, branch
`codex/langgraph-synthesis-harness`. Read `AGENTS.md` and `CONTEXT.md` and
follow them. Never touch `main` or `/Users/vishal/Desktop/agent_simulator`.

**A note on language.** `docs/plans/break-the-agent.md` is written in plain
English on purpose. Anything written *into the repo proper* uses the house
vocabulary as normal.

## Where things stand

- Offline tests: **1047 passing**, `ENVIRONMENT.md` holds that number and
  `make test` fails on any drift. Run it before you change code, and never edit
  a tracked file while it is running.
- Eight commits on top of `9b53966`: `3bf7e44` ADR 0008 and the Openings finder,
  `38d2861` the Ladder and its four Rungs, `4d6cf1f` the climb decision,
  `3dceb3e` the compound record, `b80d293` the Anthropic client, `ce7257a`
  realizing a Ladder, `6305dcc` the probe command, `cba3305` the live Rung
  provider, `5f1f428` the four realized Rungs. The last three are **not yet
  pushed**.
- **The four Rungs exist.** Four live `gpt-5.5` calls, four accepted on the
  first attempt, in
  `synthesized_journey_scenarios/appointment-rescheduling/ladder-identify-existing-appointment/`.
  That is the only live spend so far.
- **Nothing has been played.** No Episode, no Simulated user, no Judge call.

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
  difficulty directions, `realize_ladder`, both narrative providers
  (`StubLadderNarrativeProvider`, `LiveLadderNarrativeProvider`), and
  `IDENTIFY_EXISTING_APPOINTMENT`, the four Rungs against rule 1.
- `agentsim/journey/climb.py` — the climb decision, with `play` injected.
- `scripts/journey_harness.py probe` — the plumbing that was missing: it loads a
  realized Ladder set, resolves each Scenario back to its Rung *by number*, and
  gives `climb` a `play` that is `run_episode` then `evaluate_episode`. Writes
  `journey_probes/<probe_id>/climb.json` and
  `rungs/rung-<n>/seed-<m>/` Episode directories. See
  `docs/solutions/probe-plays-episodes-without-the-run-machinery.md`.
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
- **Rungs never reuse or edit `_COMPLICATION_DIRECTION` or `SYSTEM_PROMPT`.**
  Those resolve their own difficulty and describe the measuring mode's customer.
- **Customer model: `claude-opus-5`. Judge: `gpt-5.5` (calibration-locked).
  Generator: `gpt-5.5`. One Seed per Rung to begin with.** The user chose all
  four on 2026-09-25.
- **No stub rehearsal.** A climb has no stopping logic of its own to prove, and
  a scripted agent answers every Rung the same way.
- **A Probe does not use the Run's machinery** and its Episodes are evidence, so
  `journey_probes/` is not git-ignored the way `journey_runs/` is.

## What to do next

1. **The user reads the four Rungs.** ADR 0008 puts that human read in place of
   the self-check, and it has not happened yet. Print them with the difficulties
   each Rung carries beside the narrative; the four files are in the set
   directory above.
   - **One thing that read should settle.** Rung 3's traits let Maya give her
     confirmation code if asked, and `HSD-4822` identifies `A-1002` uniquely.
     The `will-not-choose` direction withholds the provider and the date and says
     nothing about the code, and the code is one of the Ladder's grounded facts,
     so the model was entitled to use it. An agent that simply asks for it
     identifies the appointment without her ever choosing, and the Rung built to
     end `task_incomplete` may end `pass`. Rung 4 does not offer it. Changing
     this is a change to the Ladder (the direction text or the grounded facts),
     and re-realizing costs four more `gpt-5.5` calls, not two: `realize_ladder`
     never overwrites a set, so the committed one would have to go.
2. **The user's Persona-fidelity spot-check** of the Opus customer. `AGENTS.md`
   requires it before reported use, and it is a human read — not yours to do.
   Records go under `journey_spot_checks/`. It needs an Episode to read, so in
   practice it follows the first climb.
3. **Climb rule 1 against the LangGraph agent.** The command exists:

       set -a; . ./.env; set +a
       scripts/journey_harness.py probe \
         --journey journeys/appointment_rescheduling \
         --scenarios synthesized_journey_scenarios/appointment-rescheduling/ladder-identify-existing-appointment \
         --service-url <the agent service> \
         --probe-id climb-01 \
         --simulator-model claude-opus-5

   Cost is up to four Episodes (one Seed each), each a conversation of up to
   twelve Turns plus one Judge call. The climb stops at the first Rung not
   survived, so it may be fewer.
4. Then: a Spot-check-style record for a ruling on one suspected finding
   (original plan step 3), and the design note (step 4).

## Landmines — each of these cost a session time

- **A prompt constant is not evidence of what is sent.** `LADDER_SYSTEM_PROMPT`
  existed and nothing sent it; the only live provider sends the measuring mode's
  prompt, which directs one Complication. The four Rungs would have come back
  valid and wrong. `AGENTS.md` now carries the rule, and a client double pins
  the prompt.
- **Do not claim a guard is missing from a document's wording.** An earlier
  session reported that a Simulated user could quote a Fixture id; two guards
  already existed and a test already pinned one.
- **Measure the baseline, do not predict it.** Writing a guessed pass count
  into `ENVIRONMENT.md` fails `make test`. Run the suite, read the number,
  then write it.
- **A constrained lockfile recompile.** `uv pip compile -c requirements.lock`,
  or an approved single dependency also drags `openai` and six transitive pins.
- **The offline narrative stub cannot realize a Rung** — it reads the measuring
  mode's single `complication_direction`. Use `StubLadderNarrativeProvider`.
- **Rungs 3 and 4 share two directions.** A test or a loader that finds a Rung
  by matching its prose will silently select the wrong one. Resolve a Rung by
  its number — `ladder_and_rung_for` reads `spec_id`.
- **Realizing a Ladder aborts on a Rung that cannot be realized**, rather than
  leaving a gap. A Ladder missing Rung 2 is not a shorter Ladder.
- **A harness failure inside a climb's `play` aborts the climb**, and is not an
  Episode error. A Run absorbs one and carries on; a climb has no Episode to
  call unreadable, so it keeps what it wrote and says `aborted`.

## Still open

- **Rung 3 hands over a disambiguating fact.** See step 1 above. Not decided.
- **Seeds.** One for now. A single Seed cannot say whether a break is reliable,
  which is the number a reviewer wants; `--seeds 0,1,2` is already there for
  when it matters.
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
- **Nothing renders a Probe's transcript for reading.** A human ruling on a
  finding reads `transcript.jsonl` and `normalized_trace.json` as they are.

## Housekeeping

- The ignored `.env` is in both repositories. Export with
  `set -a; . ./.env; set +a`; never print a key. Both `OPENAI_API_KEY` and
  `ANTHROPIC_API_KEY` are needed now.
- **No live model calls** without the user explicitly asking.
- This is a git worktree sharing a stash stack. Never use bare `git stash`.
- Run the `compound` skill before ending a session that implemented, debugged
  or reviewed anything, and commit its outputs.
