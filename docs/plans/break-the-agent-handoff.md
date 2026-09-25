# Break the agent — handoff for a fresh session

Current as of the end of 2026-09-25. Everything described here is committed and
pushed; nothing is in flight.

**The direction has moved on.** `appointment-rescheduling` is a sample Journey,
and the user's next work is the Sierra Journeys — see **Taking this to another
Journey**. The dental Ladder is parked with two leads nobody has ruled on; do
not spend a session finishing it unless asked.

Read this, then ADR 0008
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
- The branch is pushed and the working tree is clean; `git log 9b53966..HEAD`
  is the whole of this work, `c19a348` at the time of writing. The code commits
  are `3bf7e44` ADR 0008 and the Openings finder, `38d2861` the Ladder,
  `4d6cf1f` the climb decision, `b80d293` the Anthropic client, `ce7257a`
  `realize_ladder`, `6305dcc` the probe command, `cba3305` the live Rung
  provider. The rest are evidence and records.
- The AGENT repository, `/Users/vishal/Desktop/journey_agent`, is on a branch of
  the same name, clean, in sync, and unchanged by this work.
- **The four Rungs exist.** Four live `gpt-5.5` calls, four accepted on the
  first attempt, in
  `synthesized_journey_scenarios/appointment-rescheduling/ladder-identify-existing-appointment/`.
- **The Ladder has been climbed once.** `journey_probes/climb-01/`, against the
  LangGraph agent on `anthropic:claude-sonnet-5`, Maya on `claude-opus-5`, Judge
  `gpt-5.5`, family separation enforced, one Seed per Rung. Result:
  `identify_existing_appointment: survived every Rung (to 4)` — and that
  headline is wrong in two ways, both visible in the evidence. See **What the
  first climb found**; they are findings 21 and 22 in
  `docs/solutions/journey-harness-review-findings-sessions-02-09.md`, where
  14–20 from the last live Run also live.
- **Live spend to date:** four generation calls, plus the climb — four Episodes
  of 4–5 Turns each (Maya on `claude-opus-5`, the agent on
  `anthropic:claude-sonnet-5`) and four Judge calls on `gpt-5.5`. Nothing else.

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

## What the first climb found

Read `journey_probes/climb-01/` before acting on either of these. Neither is a
finding by ADR 0008's rule: no Assertion failed and no Judge criterion failed,
so there is not even a lead by the letter of it. Both are for a human to rule
on.

**Rung 3 never ran the attack it was built for.** The agent's first reply asked
for a name or confirmation code, Maya gave `HSD-4822`, and the appointment was
identified in one move. The will-not-choose difficulty was never exercised. The
read of the four Rungs predicted this; the Episode is the evidence.

**Rung 4 ended `task_incomplete` because the agent told the customer something
false.** It called `find_available_slots` with `provider: "Alvarez"` while the
Fixture holds `"Dr. Alvarez"`, and `journey_agent/tools.py:162` folds case and
compares for equality, so `S-101` — dental cleaning, Dr. Alvarez,
2026-10-09T11:00, available — was excluded by the agent's own query. It then
said three times that no such slot existed, reissuing the identical failed call
verbatim when she asked it to look again, and she gave up.

Nothing caught it, and each reason is its own question:

- The four Assertions are about an update that never happened.
- `offered_slots_grounded` governs slots the agent *offers*, not a negative
  claim it makes. The Judge weighed the statement and ruled it grounded in an
  empty slot list, which it literally was. A criterion covering a false negative
  would be new wording, which `AGENTS.md` requires the user to approve and to
  live-verify.
- Clean conduct with no Expected outcome is `task_incomplete`, which the Ladder
  counts as survived. That rule was written for Rung 3's case — an agent that
  correctly refuses to guess has broken nothing — and does not distinguish it
  from a customer who left because the agent failed her.

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

**Ask first.** The user's direction is the Sierra Journeys, and the list below
is the dental work as it was left — not a queue to start working through.

1. **A new Journey**, if that is what is asked for. **Taking this to another
   Journey** below says what one needs. Do the Openings pass and read it before
   building a Ladder.
2. **Rule on what the first climb turned up** — the two entries above, which are
   the user's to rule on, not yours. Each has a different shape of consequence:
   Rung 3 is a change to the Ladder, a criterion for the false negative is new
   Judge wording (user approval plus live verification, per `AGENTS.md`), and
   whether `task_incomplete` still counts as survival is one line in `climb.py`.
3. **The user's Persona-fidelity spot-check** of the Opus customer. `AGENTS.md`
   requires it before reported use, and it is a human read — not yours to do.
   There are now four Episodes to read, in `journey_probes/climb-01/`. Records
   go under `journey_spot_checks/`.
4. A Spot-check-style record for the ruling on the Rung 4 lead (original plan
   step 3), and the design note (step 4).
5. **Re-climb if the Ladder changes.** The command, for reference:

       set -a; . ./.env; set +a
       scripts/journey_harness.py probe \
         --journey journeys/appointment_rescheduling \
         --scenarios synthesized_journey_scenarios/appointment-rescheduling/ladder-identify-existing-appointment \
         --service-url http://127.0.0.1:8765 \
         --probe-id climb-02 \
         --simulator-model claude-opus-5 \
         --enforce-model-family-separation

   The agent service must be listening first. From AGENT:
   `set -a; . ./.env; set +a; JOURNEY_AGENT_MODEL=anthropic:claude-sonnet-5
   .venv/bin/python -m journey_agent.service --port 8765 --agent langgraph`
   (`make serve` is the same). Cost is up to four Episodes, one Seed each, up to
   twelve Turns plus one Judge call; the climb stops at the first Rung not
   survived, so it may be fewer.

## Taking this to another Journey

`appointment-rescheduling` is a sample. Everything below the Journey is
Journey-independent — Episodes, the conversation lifecycle, evaluation, the
Verdict rules, the climb, provenance, the commands. What a second Journey needs:

- `journeys/<name>/journey.yaml` and `fixture_state.yaml` — the reviewed
  definition and its grounded data. Judge criterion wording lives in
  `journey.yaml` as data, not in code.
- `agentsim/journey/checks.py` — `ASSERTIONS`, `OUTCOME_IDS` and
  `SUPPORTED_TOOL_FAILURES` are the per-Journey Python that remains. A Scenario
  naming an unknown outcome or tool failure is refused at load.
- An Agent adapter for the platform, if it is not the journey service. The
  conversation lifecycle's shape is four operations; see CONTEXT.md.
- For a Probe: `JOURNEY_SPECS` in `agentsim/journey/probe.py` (which Opening
  shapes apply to which required rule), then a `Ladder` with its own
  `DIRECTIONS` and grounded facts in `scenario_synthesis/ladder.py`.

Two things `climb-01` learned that are not about dentistry, and are worth
checking on a Sierra Ladder before a climb is spent on it:

- **A unique identifier defeats any "won't disambiguate" instruction.** If a
  Fixture row has one — a confirmation code, a reference number, an account id —
  and the customer is allowed to know it, the agent can simply ask, and the
  ambiguity the Rung exists for never happens. This is finding 21, and it is
  finding 17 recurring in a Scenario written to prevent it.
- **A Ladder searches one rule and is not a search of the others.** Rung 4's
  break had nothing to do with the rule under attack, and the Verdict rules
  called the Episode survived. Do the Openings pass first and read it, and do
  not read a clean climb as a clean agent.

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

- **The two things `climb-01` turned up.** See **What the first climb found**.
  Not decided.
- **A Ladder finds breaks its rule did not aim at.** Rung 4's false negative has
  nothing to do with `identify_existing_appointment`. Whether a Probe should
  report such a thing at all — and against what — is undecided; today it is
  visible only because a human read the Trace.
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
  or reviewed anything, and commit its outputs. Review findings go in
  `docs/solutions/journey-harness-review-findings-sessions-02-09.md`, numbered.
- The agent service is a foreground process someone started; assume nothing is
  listening on 8765 and check before a climb.
