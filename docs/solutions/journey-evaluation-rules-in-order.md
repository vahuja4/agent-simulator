---
title: Journey evaluation applies its outcome rules strictly in order, over a saved Episode
category: journey-harness
symptoms:
  - After a 500 agent_error the retrieved Trace is evidence-available yet to_trace() refuses it, so projecting the Trace before checking the stop reason raises instead of yielding error.
  - A Judge rules once on the whole conversation and names no Turn, so a Judge failure had no message or action identities to point at.
  - Evidence file paths inside FailureRecord.data differ per Episode directory and pull identical failures into different clusters.
  - A Judge answering continue on a completed conversation, or pass without affirming every criterion, had no defined outcome.
---

# Journey evaluation applies its outcome rules strictly in order, over a saved Episode

## Question

Session 06 built `agentsim/journey/evaluation.py` and
`agentsim/journey/judge.py`. The design note fixed seven outcome rules; what
happens at their edges — an unreadable Episode directory, an aborted Episode,
a Judge that answers something other than a clean pass or fail — and what
evidence does a Judge failure reference when the Judge names no Turn?

## Decision

- **Rules fire strictly in order, and the Trace is projected only after rules
  1 and 2.** Rule 0 was added: `episode.json` or `scenario.yaml` unreadable →
  `error`, with `evaluation.json` still written. Rule 1 also covers
  `status: aborted` (stop reason null) and an unknown stop reason. Rule 2 also
  covers an unreadable `normalized_trace.json`, an `unavailable` outcome gate
  and a Trace `to_trace()` refuses. Assertions are not run on incomplete
  evidence.
- **Any exception from the Judge is `error`** (rule 4), not only `LLMError` —
  the same reading session 05b took for the Simulated user.
- **Evaluation is fail-closed a second time.** A referenced criterion the
  verdict does not affirm is a `fail` whatever decision came with it, so a
  Judge that is not `JourneyJudge` cannot pass by omission. A `fail` with every
  criterion affirmed carries one failure, id `judge_decision`, so no `fail`
  reaches clustering empty.
- **A Judge `continue` is `task_incomplete`, never `pass`**, even when the
  outcome is evidenced. The prompt tells the Judge never to answer it; the
  inherited schema still allows it. `evaluation.json` `incomplete` records the
  decision, because the gate carries no `FailureRecord`.
- **A Judge failure points at the tools its criterion is about.**
  `checks.JUDGE_CRITERION_TOOLS` mirrors `AssertionSpec.tools`; the evidence is
  those tools' actions plus the user message each handled and the reply it
  produced. Identities come from the Normalized Trace, never from Transcript
  lines (user lines carry no `message_id`).
- **Evidence `files` are names relative to the Episode directory**, identical
  across Episodes, so `data` stays stable for clustering.
- **Mechanics take criteria as input.** `evaluate_episode(episode_dir, judge,
  *, criteria=criteria_for)`; `criteria_for` resolves the Scenario's criterion
  references from `checks.py`. The Judge is handed in ready-made
  (`JourneyJudge(llm, journey)`), and binds itself to the Scenario that
  evaluation loads from the Episode directory.
- **The Judge prompt holds four inputs**: Goal; referenced criteria and the
  required rules they check; transcript; projected Trace. Valid outcomes and
  permitted behavior were left out on purpose: naming the expected outcome
  would leak the controlled tool failure, and the design note lists neither.
- `JUDGE_MODEL` is the literal `gpt-5.5`; `agentsim.llm.DEFAULT_MODEL` reads
  `AGENTSIM_MODEL` and so could not be used.

## Why

Order is the only thing that keeps an infrastructure problem from reading as
an agent failure: every ambiguous case above resolves toward `error` or
`task_incomplete`, never toward `pass`, and never toward `fail` without a
recorded check id. Pointing a Judge failure at tools keeps Journey knowledge
in `checks.py` while giving a reader the update and the customer message it
followed, which is what they open first.

## What would make us revisit it

- A live Judge that answers `continue` often: map it in `JourneyJudge` or drop
  it from a Journey schema, rather than lose evidenced Episodes to
  `task_incomplete`.
- Judge criteria calibrated to need valid outcomes or permitted behavior in
  the prompt. That is a wording-level change and needs live verification.
- A second Journey: `criteria_for` reads one `checks` module; it would need a
  registry keyed by Journey.
- Clustering that splits identical Judge failures because conversations differ
  in length (the action and message ids sit in `data`).

Nothing here was run against a live Judge. The criteria are uncalibrated and
these tests say nothing about Judge accuracy.
