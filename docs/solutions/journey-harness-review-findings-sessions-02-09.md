---
title: Review findings of the LangGraph harness sessions (02–10), fixed and open
category: journey-harness
symptoms:
  - Findings surfaced by session reviews and coordinator pre-flights were scattered across closing reports and the untracked session prompts; a later reader of the branch could not tell what had been caught, what was fixed, and what was left as a known limit.
---

# Review findings of the LangGraph harness sessions, fixed and open

Recorded by session 09 (2026-09-22) at the end of the effort on branch
`codex/langgraph-synthesis-harness`, as the compound skill requires: findings
whose fixes are already committed are listed with the fix, so the record is
complete. Design contract: `docs/plans/langgraph-harness.md`.

## Question

What did the reviews across sessions 01–09 find, which of it was fixed, and
which of it stands as a known limit of the deliverable?

## Decision — the record

### Fixed, with the session that fixed it

| # | Finding | Fixed in |
|---|---|---|
| 1 | The design note's first `reschedule_goal_completion` wording made `task_incomplete` unreachable: every Turn-limit Episode would have been `fail`. Pinned to the payments `goal_completion` semantics — completion is the gate's call. | 01 / 03 (`docs/solutions/journey-goal-completion-is-the-gates-call.md`) |
| 2 | Session 02 suggested `result_available = (status == "succeeded")`, which would have turned every controlled-tool-failure Episode into `error`. Rule: it means "the raw action carries the `result` key". | 03 / 05a |
| 3 | The first 60 s / 300 s time limits were too tight for a multi-call LangGraph turn; now parameters defaulting to 120 s / 600 s — reasoned, not measured. | 05a / 05b |
| 4 | The simplify review of synthesis found six bugs (an orphaned set directory after a mid-run crash among them). | 07c (`journey-synthesis-aborted-sets-keep-evidence.md`) |
| 5 | A high-Knowledge-level customer was never shown the rule it must state; only a Goal that happened to spell it out worked. | 06b |
| 6 | Judge failure `data` carried per-Episode message and action ids, which would have split identical failures across clusters; `run` writes a clustering view without them. | 08 |
| 7 | Coordinator pre-flight of 06c: evaluation was never handed a Journey definition, and the Scenario loader checked Judge ids against the Python table 06c deleted. | 06c |
| 8 | Coordinator pre-flight of 08: `cluster_failures` clusters `fail` only, so `task_incomplete` Episodes would have been counted and listed nowhere. The report has one section per outcome. | 08 |
| 9 | A completed Run whose re-evaluation was interrupted was labelled `aborted` for good. Two facts, two fields. | 09 (`journey-re-evaluation-has-its-own-record.md`) |
| 10 | `_retrieve_and_release` promised never to raise, but the no-conversation branch saved the empty Trace unguarded: a failed `start_conversation` plus an unwritable Episode directory left no `episode.json` at all. Guarded like the other branch. | 09 |
| 11 | The "nothing imports LangGraph, LangChain or the agent" test walked `agentsim/` only; `scenario_synthesis/` and `scripts/` (the composition root) were unpinned. Widened. | 09 |
| 12 | Nothing pinned that the Judge and every `evaluate_episode` call hold the same loaded `JourneyDefinition` in `run` and `run --re-evaluate` (criterion wording lives there). Pinned by identity in `tests/test_journey_cli.py`. | 09 |
| 13 | The pinned raw-Trace samples catch drift from the HARNESS side only. `scripts/recapture_journey_agent_traces.py` re-captures them from AGENT's stub through the adapter and compares; run 2026-09-22 against AGENT `ee72c7f`: same. | 09 |

### Considered and left, with why

| Finding | Why left |
|---|---|
| Evaluation rule 3 fires on a non-empty failure list, not on `status == "failed"`. | `EvaluationCriteria.assertions` is `tuple[AssertionSpec, ...]` and `AssertionSpec.check` derives `failed` from a non-empty list, so the two cannot disagree by construction. |
| `_simulator_model` in `scripts/journey_harness.py` swallows every exception but `SimulatorConfigError` and records the model as `None`. | Deliberate: a Simulated user that cannot be built for one Scenario is that Episode's `error`, and the next Scenario still runs. With `--enforce-model-family-separation` the refusal then names "no Simulated-user model" rather than the real cause — cosmetic, noted. |
| `OPENAI_API_KEY` is checked for presence only; an invalid key fails per Episode at network time. | The design note's "one line before any network call" is about missing configuration; validity needs a call. |
| A model-written `goal` or `persona.traits` could carry outcome vocabulary ("they'll say the system is down") into the Simulated user's prompt; the lexical Sealed-world check rejects ungrounded identifiers and dates only. | Inherent to a model writing free text; automated checks on the Simulated user were rejected on 2026-09-21 (design note §12 item 3). Watch in the first live synthesis. |
| Rule 2 trusts the `evidence` block the normalizer wrote. | The normalizer is the contract owner (section 2) and is pinned against the raw samples; re-deriving it in evaluation would be a second normalizer. |
| `_write_text` for `episode.json` replaces atomically without fsync. | Same durability as every other JSON the harness writes; the fsync'd transcript is the crash record. |

### Known limits of the deliverable (not defects; stated in the final report)

Until session 10 nothing had run against a real model; a reported live Run
is blocked by the single shared OpenAI client (model-family separation) and
by the absence of any Spot-check record; Simulated-user fidelity is unchecked
by design; the agent's confirmation guard means `user_turn_before_update` can
never fail against it; the `JourneyJudge` criteria are uncalibrated; only the
Judge half of a Journey is data; Sierra needs more than the adapter; the
lexical Sealed-world check may reject honest text; the time limits and the
0.6 clustering rule are untuned.

### Session 10 — the first live development Run (2026-09-22), open

Run `live-dev-01`: four live-generated Scenarios against the LangGraph agent
on `claude-sonnet-5`, Simulated user and Judge both `gpt-5.5` — a development
Run, **not reportable**, recorded in full at
`docs/reports/live-runs/live-dev-01/README.md`. Its measurements, one Run of
four Episodes each: Sealed-world rejections 0 of 4 attempts; longest request
to the service ≤ 6.6 s against the 120 s limit, longest Episode 51.7 s
against 600 s; no `agent_error`, 4–8 customer Turns of 12; both
high-Knowledge-level customers stated their rule exactly once; all 20 Judge
rulings agreed with the session's reading; 4 pass, 0 fail. Findings, none
fixed (the session was told to report, not fix):

| # | Finding | Evidence |
|---|---|---|
| 14 | The AGENT service logs nothing per request: its whole log is the startup line, so retries and 30 s model timeouts are unobservable from outside. | the README, "What was run" |
| 15 | The agent's model is recorded nowhere: `journey_run.json`, the service's start response and the raw Trace hold the kind `langgraph` only; `report.md` says "Agent: `langgraph`". Which model the Judge graded is known only from the session README. | `grep -rl sonnet journey_runs/live-dev-01` finds nothing |
| 16 | `report.md` never says the Run is not reportable: it prints both models as `gpt-5.5` but not that they share a family, nor that `enforce_model_family_separation` was `false` (which `journey_run.json` records). | `docs/reports/live-runs/live-dev-01/report.md` |
| 17 | A generated Scenario can permit its own Complication to be bypassed: Episode 1's Goal lets the customer give "her name, confirmation code HSD-4822, or the Dr. Chen appointment details", she gave the code first, and the ambiguous-reference Complication (two appointments, the customer chooses) never occurred. Validation checks structure, not that the Goal forces the Complication. | `runs/synth-appointment-rescheduling-7c46137f7bbd-*/{scenario.yaml,transcript.md}` |
| 18 | `report.md` shows outcomes without stop reasons or expected outcomes; two of the four passes ended `user_gave_up` with the appointment unchanged (the correct `update_failed_reported`), which the outcome table alone reads as four reschedules. | `runs/*/episode.json` `stop_reason` |
| 19 | Candidate criterion-wording observation, not a disagreement: `reschedule_confirmed` does not say how a retry the agent itself offered ("Would you like me to try again?") is read when the customer answers "Try again"; the Judge and the session both read it as confirmation, a stricter reading could call it a proceed-demand from a pressure Persona. Wording changes need approval and live verification. | Episodes 2 and 4, Turns 6 and 8 |
| 20 | The medium-Knowledge evidence ("relies on the assistant for the same-service rule") was not observable in Episode 2: the customer never asked, and wrote "same svc pls". Fidelity is the user's hand check; no check exists by design. | `runs/synth-appointment-rescheduling-d7f002747aff-*/transcript.md` Turn 8 |

## Why

AGENTS.md requires compound to record review findings from the current and
carried-over sessions, fixes committed or not, so that a finding is never
lost because its code was already corrected. This effort's findings lived in
untracked session prompts and closing reports; this file is their tracked
home.

## What would make us revisit it

The first live Run (session 10, above) turned the "considered and left" rows
into one measurement each; it observed no Judge ruling variance (one Judge
call per Episode, all rulings agreed with the reading), so no N-series entry
was made. A Run with more Episodes, or a re-evaluation of `live-dev-01` that
rules differently, would be the first N-series candidate for the
`JourneyJudge`; a reported Run (family-separated Simulated user, Spot-check
records) would be the first result.
