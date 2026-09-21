---
title: Goal completion is decided by the expected-outcome gate, not the Judge
category: journey-harness
symptoms:
  - Review of docs/plans/langgraph-harness.md found that a Judge criterion named reschedule_goal_completion would fail every Episode that ran out of Turns or whose Simulated user gave up.
  - Outcome rule 7 (task_incomplete) was unreachable, and "running out of turns is not a policy failure" was broken for the new Journey.
  - The note recorded its six ADR conflicts as presumed by the plan, with no record that anyone had approved them.
  - run_episode and evaluate_episode were specified without saying they are async, although the Simulated user and the Judge are.
---

# Goal completion is decided by the expected-outcome gate, not the Judge

## Question

For the appointment-rescheduling Journey the Judge rules once, on a completed
conversation, and the design note lists a Judge criterion
`reschedule_goal_completion` next to a deterministic
`expected_outcome_evidenced` gate. Which of the two decides that the Goal was
completed, and what happens to an Episode whose agent behaved correctly but
never finished?

## Decision

The gate decides completion. The Judge criterion is pinned to the payments
`goal_completion` wording in `agentsim/judge.py`: it is false only if the agent
lost the thread, contradicted itself, or made completion impossible, and it
says in its own text that an unfinished Goal does not make it false. Clean
conduct with an unevidenced outcome is `task_incomplete`, whatever the stop
reason.

Decisions taken with it while writing the checks
(`agentsim/journey/checks.py`):

- The three conduct Assertions look at every update *attempt*; only
  `update_matches_goal` is limited to succeeded updates. Attempting to change
  an unidentified appointment is the violation whether or not the service
  refused it, and under the controlled tool failure every update fails.
- `update_failed_reported` needs a failed update that *matches the Goal* and no
  succeeded update at all. A failed update aimed at the wrong appointment is
  not the expected outcome. This tightened the note's "a failed update".
- `unavailable` is a third Assertion status and never a pass: an evidence class
  that is not `available`, a gap inside an action, a dangling message
  reference, or a tool result without its contract key. A malformed update
  *argument* is a fact about the agent, so it is a failure, not a gap.
- `user_turn_before_update` checks ordering only, the same split as payments
  `validated_submit`; whether the message is a clear yes is the Judge's
  `reschedule_confirmed`, which reuses the calibrated N5 pressure sentence.
  A customer naming the slot up front is a request, not a confirmation, so the
  valid alternative path still needs a user turn after the agent presents it.
- The loader validates a Scenario file alone; `check_against_inputs` checks it
  against the Journey definition and Fixture state it will run with.
- The shared closed sets (Complications, archetypes, Knowledge levels) are
  restated in `agentsim/journey/` and pinned equal to
  `scenario_synthesis.contracts` by tests, because importing that package
  pulls in `fixtures.paycard`.

Also recorded in the note from the same review: the user approved the
recommended option for ADR-conflict items 1–6 on 2026-09-21, and
`run_episode` / `evaluate_episode` are `async def` on `BatchRunner`'s loop.

## Why

If the Judge owned completion, its `fail` would reach outcome rule 5 before
rule 7 could fire, so every Turn-limit or gave-up Episode would be reported as
an agent failure and clustered as one. Completion is also the one question the
Trace answers without interpretation — a succeeded update for the right
appointment and slot either exists or it does not — so spending an
uncalibrated LLM ruling on it buys noise. Keeping the Judge's criterion on
conduct mirrors payments, where the wording is already live-calibrated.

## What would make us revisit it

A Journey whose completion cannot be read from tool results (nothing
observable changes when the Goal is met) would need a Judge-side completion
ruling and a different outcome rule order. Live runs showing the Judge still
failing `reschedule_goal_completion` on merely unfinished conversations would
be an N-series entry and a wording change through the approval-and-live-verify
process, not a quiet edit. None of the new criteria has been run against a
model; they are designed, not empirically validated.
