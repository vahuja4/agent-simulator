---
title: Judge criteria are data in the Journey definition; Assertions stay code
category: journey-harness
symptoms:
  - A second Journey needed a Python module for what is only criterion wording and a criterion → tools lookup table.
  - Editing a Judge criterion's wording did not change the journey_sha256 that every Scenario's provenance records.
  - Evaluation looked a Judge criterion's tools up with .get(id, ()), so an unknown criterion silently meant "about no tool".
  - The Scenario loader checked Judge criterion ids against a Python table although it holds no Journey definition.
---

# Judge criteria are data in the Journey definition; Assertions stay code

## Question

Sessions 03–06 kept the five Judge criterion texts and the criterion → tools
table in `agentsim/journey/checks.py`, following the payments precedent;
`journey.yaml` listed ids only. The Judge mechanics were already free of
appointment wording, but their content was not. The user directed on
2026-09-21 that the content move into the Journey file. Where does it live,
how does evaluation reach it, and what happens to an id nobody defines?

## Decision

- **`journey.yaml` `criteria.judge` is a list of `{id, statement, tools}`.**
  `tools` is always written; a criterion about the conversation gives `[]`.
  The loader refuses a duplicate id, an empty statement, a tool outside the
  Journey's `tools`, an unknown or missing field, and a `judge:<id>` rule
  reference to a criterion the list does not define. `criteria.assertions`
  stays a list of ids.
- **The definition hands out what the Judge half needs**:
  `JourneyDefinition.judge_criteria`, `judge_criterion(id)` and
  `criteria_for_judge(ids)` (the `agentsim.judge.Criterion` objects).
  `judge_criterion_ids` is derived from the rows, so there is one source.
- **`evaluate_episode(episode_dir, judge, journey, *, criteria=criteria_for)`**
  takes the definition as an explicit argument, and `criteria_for(scenario,
  journey)` reads the tools from it. The Judge protocol exposes only
  `judge_episode`, so reading `judge.journey` would have made every Judge
  double carry a definition.
- **Two refusals are rule 0 (`error`)**: the Scenario's `journey` is not the
  definition's `journey_id`; a Scenario Judge criterion the definition does
  not define. The mechanics also refuse handed criteria that leave a Scenario
  Judge criterion out, so the failure path indexes the tools and never
  defaults to "no tools".
- **The Scenario loader no longer checks Judge criterion ids.** It has no
  Journey definition, and a shadow id list in Python would be the table again.
  The id is caught by `check_against_inputs` and by rule 0. Consequence: in
  synthesis an unknown Judge id is rejected as `input-mismatch`
  ("criteria.judge differ"), no longer `schema-invalid`.
- **The wording did not change by a byte.** The SHA-256 of each statement was
  recorded from the Python literals at `709ab0a` and is pinned in
  `tests/test_journey_definition.py`; the Judge's whole system prompt is
  pinned in `tests/test_journey_evaluation.py`. The old and new prompts were
  compared directly before the old code was deleted.
- **Assertions stay code.** They are logic over the Normalized Trace; stating
  them as data would need a rule language, which is the deferred generic
  refactor. No registry was added.

## Why

Wording and a lookup table are data, and data belongs in the reviewed input
whose hash a Scenario's provenance records. A YAML folded scalar (`>-`) joins
lines with one space and drops the final newline, which reproduces Python's
adjacent-literal concatenation exactly — but only as long as no line is
indented further and no blank line appears, so the hashes are the guard, not
the convention. A missing criterion is an error rather than an empty tool
list because the two mean different things: `[]` is a statement about the
criterion, absence is a broken reference.

`tests/test_journey_evaluation.py` writes a second, tiny Journey definition
inside a test (two new criteria, one tool) and has the same `JourneyJudge`
and `evaluate_episode` prompt with it, rule on it and point a failure at the
right actions with no Python added. That test also shows the limit: the tiny
Journey must still name an appointment Assertion, an appointment tool and an
appointment outcome id, because `criteria.assertions` and `valid_outcomes`
are checked against `checks.py`.

`journey_sha256` changed because `journey.yaml` changed. No synthesized set is
committed, so nothing was invalidated. The fixed-seed Scenario-id digest did
not move: a Scenario id does not hash criterion wording.

## What would make us revisit it

- A second real Journey: the Assertion half, `OUTCOME_IDS` and
  `SUPPORTED_TOOL_FAILURES` are still one module's, and the loader requires a
  non-empty `criteria.assertions` drawn from it.
- A criterion that needs more than wording and tools — a per-criterion
  severity, or evidence narrower than "every action of these tools".
- A wording change: it needs approval (AGENTS.md), live verification before
  its phase closes, and the statement hash and the system-prompt hash updated
  in the same commit.
- A caller that evaluates Episodes of several Journeys in one pass: it must
  choose the definition per Episode; rule 0 refuses a mismatch rather than
  guessing.

Nothing here was run against a live Judge. The criteria are uncalibrated and
these tests say nothing about Judge accuracy.
