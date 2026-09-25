---
title: A Probe Rung realizes an ordinary Synthesized Journey Scenario; Rungs carry their own difficulty directions and never edit the measuring mode's
category: journey-harness
symptoms:
  - A session wants a Rung to carry several difficulties and proposes adding a field to the Scenario schema, or a new `origin` value beside `synthesized`.
  - A Rung reuses `_COMPLICATION_DIRECTION` and every Rung of the Ladder behaves the same, because that direction resolves its own difficulty.
  - A Ladder is realized live through `journey_synthesis.LiveNarrativeProvider`, and every Rung comes back carrying only its primary Complication.
  - A session plans to prove the climb against the scripted stub agent first, carrying the step over from the superseded in-conversation probe plan.
  - A Rung's Scenario file names one Complication and a reader cannot tell which other difficulties it carries.
---

# A Probe Rung realizes an ordinary Synthesized Journey Scenario

## Question

ADR 0008 has a Rung carry several difficulties at once, and `run_episode`
writes the Scenario it played back out "in the form `load_journey_scenario`
reads" (`agentsim/journey/episode.py:302`). That loader is strict: it refuses an
unknown field, and `_parse_synthesis` requires `origin: synthesized` with real
provenance hashes. So how does a Rung become something the existing machinery
can play, without widening shared validation or lying about where it came from?

## Decision

- **A Rung realizes an ordinary Synthesized Journey Scenario.** It goes through
  `journey_synthesis.scenario_document`, `validate_scenario_document` and the
  narrative Sealed-world check unchanged: `origin: synthesized`,
  `qualification: none`, real hashes. Nothing in `agentsim/journey/scenario.py`
  is widened, and no new `origin` value exists. Chosen by the user on
  2026-09-25 over two alternatives: a new `origin` value (widens shared
  validation and needs the curated loader's fail-closed behavior re-checked),
  and hand-written files keeping `origin: synthesized` untruthfully.
- **The Rung specification is the record of every difficulty.** The Scenario's
  own `complication` names the primary one only, so ADR 0005's
  one-value-per-Scenario rule is untouched. `set_id` names the Ladder and
  `spec_id` names the Rung (`rung-<n>`), and `ladder.ladder_and_rung_for`
  resolves a realized Scenario back to the `RungSpec` that states all of them.
  A Rung is never a Coverage cell, Candidate or denominator.
- **Rungs carry their own directions in `scenario_synthesis/ladder.DIRECTIONS`
  and never reuse or edit `_COMPLICATION_DIRECTION`.** The measuring mode's
  directions resolve their own difficulty — the ambiguous-reference one ends
  "picks the right one when the agent asks" — which describes the measuring
  mode's customer and is exactly Rung 1. A Ladder needs harder variants of one
  Complication, so it states its own. Editing the shared table would silently
  change every existing Scenario's meaning.
- **A Rung's provider is its own, live as well as offline.**
  `LiveLadderNarrativeProvider` exists for the reason
  `StubLadderNarrativeProvider` does: the measuring mode's providers send
  `SYSTEM_PROMPT`, which directs one Complication and never mentions
  `difficulty_directions`. A Rung realized under it comes back a perfectly valid
  Scenario carrying its primary Complication and none of the difficulty stacked
  on it — Rungs 2, 3 and 4 quietly reduced to Rung 1, with nothing downstream
  able to tell. A client double pins which prompt is sent, because the offline
  stub's passing test says nothing about the live path.
- **A direction may only name values the Ladder's grounded facts contain.**
  `check_ladder` refuses one that does not, so a difficulty is never realized by
  telling the model a fact the customer was never given.
- **The required rule under attack is withheld from the narrative request,**
  with the tool failures, the expected outcome and the checks. A customer
  briefed on which rule to break stops being one a real business could receive,
  which is ADR 0008's second condition.
- **No stub rehearsal before the real agent.** The superseded plan proved the
  probe stopped on its own against the scripted stub, because that design let
  the Simulated user decide when to stop. A climb is a loop over a fixed list of
  Rungs, each an ordinary Episode under the existing Turn and time limits, so
  there is nothing to prove. A scripted agent also answers every Rung the same
  way, which makes it a poor test of a Ladder while still costing real Simulated
  user calls. The climb decision is proven offline instead, with `play`
  injected (`tests/test_journey_climb.py`).

## Why

Everything downstream of a Scenario — the strict loader, the Episode record,
evaluation, reporting, the provenance hashes — already works, and works because
there is exactly one kind of Scenario on this path. Widening that for a Probe
would put a second kind into every one of those code paths in exchange for one
field, and the field is not needed: the Ladder definition is committed, and the
Scenario points back at it.

Keeping the measuring mode's directions untouched is the same argument as not
widening `SIMULATED_USER_STOP_REASONS`. The text is handed to the model; change
it and every earlier Scenario means something slightly different, and nothing
fails to tell you.

## What would make us revisit it

- Rungs are generated at a volume where the Ladder definition living in Python
  rather than a data file becomes the bottleneck. Then it becomes a committed
  file with a loader, and this decision is about the Scenario it produces
  either way.
- A Coverage report is found counting Rung Scenarios. That should be impossible
  — they are never admitted — but if a counter ever reaches them, an explicit
  exclusion belongs in the counter, not a change here.
- A second Journey's Ladder needs a difficulty that is not a Complication or a
  Persona archetype. `Direction.axis` has exactly those two values today.
- Per-Turn Trace retrieval becomes available. It does not change how a Rung is
  made, but it would let a climb stop inside a Rung rather than after it.
