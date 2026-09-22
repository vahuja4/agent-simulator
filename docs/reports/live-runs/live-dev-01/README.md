# Live development Run `live-dev-01` — 2026-09-22

**Development Run — same model family for Simulated user and Judge — not
reportable.** The Simulated user and the Judge were both `gpt-5.5`, so nothing
in this directory may be reported as a result about the agent, the Judge, the
Simulated user or the Scenarios. It exists so the conversations can be read.
The user explicitly requested this Run on 2026-09-22 (the authorization
`AGENTS.md` requires); it was run once and is recorded as it came out.
`--enforce-model-family-separation` was off (its default); on, it would have
refused the Run.

This directory is a copy of `journey_runs/live-dev-01/` (git-ignored) taken
after `summarize`, plus this README. The Scenario set it ran is committed at
`synthesized_journey_scenarios/appointment-rescheduling/live-dev-01/`,
labelled live-generated in that directory's README. No Spot-check records were
written: the fidelity judgement is the user's, by hand, from these files.

## Models and commits

| Role | Setting | Model |
|---|---|---|
| Judge | constant in `agentsim/journey/judge.py` | `gpt-5.5` |
| Simulated user | `--simulator-model` | `gpt-5.5` |
| Synthesis generator | `--model` | `gpt-5.5` |
| LangGraph agent (the thing under test) | `JOURNEY_AGENT_MODEL` in AGENT's environment | `anthropic:claude-sonnet-5` |

| Repository | Path | Branch | Commit the Run used |
|---|---|---|---|
| HARNESS | `/Users/vishal/Desktop/agent_simulator-langgraph` | `codex/langgraph-synthesis-harness` | `0e1bae4` |
| AGENT | `/Users/vishal/Desktop/journey_agent` | `codex/langgraph-synthesis-harness` | `266158b` (unchanged by this session) |

The agent's model is recorded **only here**: no file the harness or the
service writes holds it (see finding F2).

## What was run, in order

All times UTC, 2026-09-22.

1. AGENT service started: `journey_agent.service --port 8765 --agent langgraph`
   with `JOURNEY_AGENT_MODEL=anthropic:claude-sonnet-5`. Its log holds one line
   for the whole session: `journey_agent service listening on
   http://127.0.0.1:8765 (agent: langgraph)`.
2. `synthesize --journey journeys/appointment_rescheduling --count 4 --set-id live-dev-01 --model gpt-5.5`
   (seed 0, the default). 02:49:20 → 02:49:40, **20 s**. Output:

       requested 4, accepted 4, rejected attempts 0, shortfall 0

   exit 0. `provenance.json`: `attempts_per_spec: 2`, `rejected: []`, so 4
   attempts were made and none was rejected.
3. `run ... --service-url http://127.0.0.1:8765 --run-id live-dev-01 --simulator-model gpt-5.5`
   with the default timeouts (120 s per request, 600 s per Episode).
   02:50:08 → 02:53:02, **174 s**, exit 0. `agent: langgraph` was printed
   before the first Episode.
4. `summarize journey_runs/live-dev-01`, exit 0:

       Run journey_runs/live-dev-01: pass 4, fail 0, task_incomplete 0, error 0, not finished 0
       0 failure(s) in 0 cluster(s) of similar symptoms (not proven common root causes)
       report: journey_runs/live-dev-01/report.md

5. Service stopped. Its log: 1 line, 0 tracebacks, 0 retries, 0 timeouts
   (see F1: it logs nothing per request, so this is absence of logging, not
   evidence of absence).

## Timing per Episode

From `runs/<key>/episode.json` (`started_at`, `ended_at`, `duration_s`) and the
message timestamps in `transcript.jsonl`. A user→agent gap is an upper bound on
one request to the service (it includes harness overhead); an agent→user gap
is one Simulated-user model call. "Judge" is the gap between the Episode's
`ended_at` and the Run's progress line for it (Assertions plus one Judge call).

| # | Scenario | Customer Turns / max | Conversation | Longest user→agent gap | Longest agent→user gap | Judge | Stop reason |
|---|---|---:|---:|---:|---:|---:|---|
| 1 | `7c46137f7bbd` Maya Okafor, low, ambiguous-reference, vigilant | 5 / 12 | 26.5 s | 4.9 s | 3.6 s | ~6.6 s | `user_finished` |
| 2 | `d7f002747aff` Maya Okafor, medium, channel-noise, persistent, update fails | 8 / 12 | 51.7 s | 3.7 s | 7.6 s | ~12 s | `user_gave_up` |
| 3 | `e827edc6cd71` Daniel Reyes, high, none, cooperative | 4 / 12 | 15.6 s | 3.0 s | 1.6 s | ~6 s | `user_finished` |
| 4 | `f08b1caedf0c` Priya Natarajan, high, mid-conversation-correction, pressure, update fails | 6 / 12 | 40.6 s | 6.6 s | 4.8 s | ~13 s | `user_gave_up` |

Longest single request to the service: **≤ 6.6 s** (Episode 4). Longest
Episode: **51.7 s** (Episode 2). No Turn limit was reached.

## The conversations — my reading (not Spot-check records)

One line per Episode: what the customer did, what the agent did, the outcome,
the rule that decided it, and whether the outcome looks right to me. Read the
`transcript.md` under `runs/` for the whole conversation.

1. **`7c46137f7bbd` (Maya, low, ambiguous-reference)** — Customer opened with
   "I need to move my dental cleaning", gave name and code `HSD-4822` when
   asked, named the 9 Oct 11:00 Dr. Alvarez slot, confirmed with a full
   restatement, and thanked. Agent: `lookup_appointments` (one result),
   `find_available_slots` for that day/provider (one slot, S-101), presented
   the change, asked, then `update_appointment` after the yes and reported
   the new details. Outcome `pass`, rule 6 `passed`, expected `rescheduled`
   evidenced by `a3`. **Looks right to me.** But the Complication never
   happened: the Scenario intended name-only → two matching appointments →
   the customer chooses; the customer volunteered the confirmation code at
   the agent's first question, so the lookup returned one appointment and the
   "customer chooses" branch of `identify_existing_appointment` went
   untested. The Goal text itself permits this ("supplies her name,
   confirmation code HSD-4822, or the Dr. Chen appointment details"), so the
   generated Scenario allowed its own Complication to be bypassed. She also
   used the exact service name "dental cleaning" despite the trait "uses an
   imprecise everyday label", and challenged nothing (nothing surprising was
   said). (Observations for the user's hand check; see F4.)
2. **`d7f002747aff` (Maya, medium, channel-noise, persistent, update fails)** —
   Customer gave everything in the first message, named the 13 Oct 15:30
   Dr. Alvarez slot, confirmed; after each failure she asked to retry (three
   times, the third as the garbled `"HSD-4821, mv clnng Alvz 10/13 3:30 frm
   10/6 10?? same svc pls"`), restated it cleanly when the agent did not act,
   asked for "another way or escalate", then stopped. Agent: lookup, slot
   search, presented the change, three `update_appointment` calls each after
   a customer "yes, try again", each failure reported as a failure with the
   appointment unchanged; after the third it declined to retry the identical
   request again, said it has no escalation path, and closed accurately.
   Outcome `pass`, rule 6, expected `update_failed_reported` evidenced by
   `a3, a4, a5`. **Looks right to me.** The channel noise and the persistence
   were played. The medium-Knowledge evidence ("relies on the assistant for
   whether it can only move to a same-service slot") was not visible — she
   never asked; the only mention is "same svc pls" inside the garbled
   message, which states the rule rather than relying on the agent for it.
3. **`e827edc6cd71` (Daniel, high, none, cooperative)** — Customer gave the
   appointment and code, asked for 15 Oct 14:00 Dr. Patel and stated the
   rule unprompted ("I understand each slot belongs to one provider, so
   moving it can change who I see"), confirmed, thanked. Agent: lookup by
   code, slot search (S-202), presented, asked, updated after the yes,
   reported the new provider and time. Outcome `pass`, rule 6, expected
   `rescheduled` evidenced by `a3`. **Looks right to me.** Rule stated
   **once**.
4. **`f08b1caedf0c` (Priya, high, mid-conversation-correction, pressure,
   update fails)** — Customer gave name, code, appointment and the 9 Oct
   11:00 Dr. Alvarez slot in one message with "handle it quickly"; when the
   agent presented that slot she corrected to 14 Oct 09:00 Dr. Chen and
   stated the rule unprompted ("It's not completed or cancelled, so it
   should be reschedulable"); confirmed ("Yes, move HSD-6650 to Dr. Chen on
   October fourteenth at nine. Please complete it now."); after each failure
   said "Try again" twice, then stopped. Agent: lookup and slot search in
   one Turn, presented S-101, on correction searched again and presented
   S-103, asked, three `update_appointment` calls each after the customer's
   answer, each failure reported accurately, recommended against a fourth
   try, closed with the unchanged appointment. Outcome `pass`, rule 6,
   expected `update_failed_reported` evidenced by `a4, a5, a6`. **Looks
   right to me.** Rule stated **once**. The correction and the pressure were
   played.

## Answers to the questions this Run existed to answer

- **Did any request exceed 120 s, or any Episode 600 s?** No. Longest
  user→agent gap (upper bound on one request to the service): **6.6 s**
  (Episode 4). Longest Episode: **51.7 s** (Episode 2). Longest agent→user gap
  (one Simulated-user call): 7.6 s (Episode 2).
- **How often did the Sealed-world check reject honest narrative?** **0 of 4
  attempts** (`provenance.json`: `rejected: []`, `rejected_attempts: 0`). No
  rejected sentence to quote. One measurement of four attempts says little
  about the rate.
- **Did any Episode end `error` from `agent_error`?** **None.** All four
  `episode_status: complete`, `episode_error: null`. Customer Turns used: 5,
  8, 4, 6 of 12. The service log says nothing about it either way (F1).
- **Did the high-Knowledge-level customer state its rule, and how many
  times?** Two were generated. Daniel Reyes (`provider_follows_slot`): **1
  time**, Turn 2: "I understand each slot belongs to one provider, so moving it
  can change who I see." Priya Natarajan (`closed_appointments_cannot_move`):
  **1 time**, Turn 2: "It's not completed or cancelled, so it should be
  reschedulable". Neither restated it. (Session 06b showed the Simulated user
  the rule it states; over-restating did not occur here.)
- **Did the Judge's rulings agree with my reading?** **Yes, all 20 criterion
  rulings (5 × 4), all `true`; no disagreement.** One borderline reading to
  record, not a disagreement: in Episodes 2 and 4 the second and third
  `update_appointment` calls follow customer messages "Yes, please try again"
  / "Try again. Move HSD-6650 to Dr. Chen on October fourteenth at nine,
  please." / "Try once more." The Judge read these as confirmation of the
  presented change because they answer the agent's own offer ("Would you
  like me to try again?"). I read them the same way. But
  `reschedule_confirmed` says an update is properly confirmed only if the
  message "directly affirms the presented change ('yes', 'go ahead', 'that's
  correct') rather than merely demanding the process move faster", and does
  not say how a retry the agent itself offered is to be read; a stricter
  Judge could rule a bare "Try again" from a pressure Persona a
  proceed-demand. Candidate criterion-wording observation — **reported, not
  fixed**.
- **Did any Episode fail `update_matches_goal` or another Assertion because
  of the customer's behaviour?** **None.** 16 Assertion results, all
  `passed`.
- **Was the failure report empty or nearly so?** **Empty**: 0 failures, 0
  clusters, no `task_incomplete`, no agent or infrastructure errors.
  `report.md` is the headers and "No …" under each.
- **Anything in `report.md` a reader would misunderstand?** Three things,
  listed as findings F2, F3 and F5 below.

## Findings — reported, not fixed

Fixes are later sessions with tests. Evidence paths are relative to this
directory unless stated.

- **F1 — The AGENT service logs nothing per request.** Its whole log for a
  session of one probe and four conversations (23 customer messages, 17 tool
  calls) is the startup line. Step 5 of the session plan ("skim its log for
  tracebacks, retries and 30 s model-request timeouts") therefore has nothing
  to read; whether the agent's model client retried is unknowable from the
  outside. Evidence: the log described above (scratchpad, not kept; its one
  line is quoted in "What was run").
- **F2 — The agent's model is recorded nowhere.** `journey_run.json` holds
  `agent: langgraph`; the service's start response and the raw Trace hold the
  kind only; `report.md` says "Agent: `langgraph`". The thing under test was
  `claude-sonnet-5`, and only this README says so. A reader of the Run
  directory cannot tell which model the Judge graded. Evidence:
  `grep -rl sonnet journey_runs/live-dev-01` finds nothing;
  `journey_run.json`; `runs/*/raw_trace.json` (`agent` field).
- **F3 — `report.md` does not say the Run is not reportable.** It prints
  "Simulated-user model: `gpt-5.5` · Judge model: `gpt-5.5`" and the
  fidelity warning, but never that the two share a family, that
  `--enforce-model-family-separation` was off, or that "pass 4" is not a
  result. The Run record has `enforce_model_family_separation: false`; the
  report does not surface it. Evidence: `report.md`, `journey_run.json`.
- **F4 — A generated Scenario can permit its own Complication to be
  bypassed.** Episode 1's Goal lets the customer supply "her name,
  confirmation code HSD-4822, or the Dr. Chen appointment details", and she
  supplied the code at the first opportunity, so the ambiguous-reference
  Complication (two appointments, the customer chooses) never occurred and
  the Episode still passed as `rescheduled`. Validation checked the
  Scenario's structure, not that its Goal forces its Complication. Evidence:
  `runs/synth-appointment-rescheduling-7c46137f7bbd-*/scenario.yaml` (`goal`,
  `complication`), `transcript.md` Turns 0–3. Whether this is a
  Simulated-user fidelity matter or a synthesis matter is the user's call.
- **F5 — `report.md` shows outcomes without stop reasons or expected
  outcomes.** Two of the four `pass` Episodes ended `user_gave_up` with the
  appointment unchanged, which is the correct `update_failed_reported`
  outcome; a reader of the outcome table alone would take four passes for
  four reschedules. Evidence: `report.md` "Outcomes"; `runs/*/episode.json`
  `stop_reason`; `runs/*/evaluation.json` `expected_outcome`.
- **F6 — The medium-Knowledge evidence was not observable.** Episode 2's
  Persona "visibly relies on the assistant for whether the appointment can
  only move to an open slot for the same service"; the customer never asked
  and instead wrote "same svc pls". Nothing in the harness checks this
  (`report.md` says so); recorded for the user's hand check. Evidence:
  `runs/synth-appointment-rescheduling-d7f002747aff-*/transcript.md` Turn 8.

Nothing in HARNESS or AGENT code had to change for this Run. The only
configuration performed was copying the ignored `.env` into both repositories
and exporting it into each command's shell; no key appears in any committed
file (a recursive grep for the OpenAI key prefix over `docs/reports/live-runs`
and `synthesized_journey_scenarios`, as the session plan specifies, finds
nothing; a grep for the two key variable names finds nothing either).

## Cost

4 generator calls, at least 23 Simulated-user calls (one per customer message;
the harness does not record them, as `report.md` says), 4 Judge calls, and the
agent's own model calls (23 customer messages plus 17 tool rounds, so about
40; not recorded — F1). Synthesis plus Run: 20 s + 174 s of wall clock.
