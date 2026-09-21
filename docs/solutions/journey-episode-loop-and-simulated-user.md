---
title: The Journey Episode loop saves first, retrieves last, and tells the Simulated user only what a customer knows
category: journey-harness
symptoms:
  - Session 05b had to decide what the Simulated user's knowledge text looks like when grounded-fact paths (which hold Fixture ids) may not be shown.
  - The payments simulator prompt says "never explain policies", which contradicts a high Knowledge level Persona that states a rule unprompted.
  - A persistent Persona "re-attempts after a refusal", which a naive "stop when the agent refuses" rule would cut short.
  - The design note listed normalized_trace.json unconditionally but did not say what is written when start_conversation itself fails.
  - AGENTS.md requires an aborted record after an unexpected failure; the design note's six stop reasons have no value for one.
---

# The Journey Episode loop and its Simulated user

## Question

How does `run_episode` keep its evidence on every path, and what may the
`JourneySimulatedUser` prompt say without leaking the evaluation or fighting
an existing Persona?

## Decision

**Simulated user.** Knowledge text is every grounded fact's value under a
customer-facing heading; the Fixture binding only picks the heading ("the
appointment you want to move", "the new time you want", "another … you know
about"). Paths, Fixture ids, checks, the Expected outcome and `tool_failures`
never reach the prompt. Other-entity facts are kept. Date-times are written
out with their weekday, as written. Today's date is not told (it is not a
grounded fact) and relative dates are forbidden. Stopping is a schema field,
`stop_reason: none | goal_achieved | gave_up`, not a sentinel. The payments
confirmation-gate paragraph and its per-turn reminder are copied verbatim and
pinned by a test.

**Conflict check against existing Personas** (AGENTS.md; done 2026-09-21
against the four archetype directions, the three Knowledge-level directions
and the seven supported Complication directions in
`scenario_synthesis/journey_synthesis.py`, which are what every Journey
Persona is written from; the payments Personas under `scenarios/` are never
played by this class and `agentsim/simulator.py` is unchanged):

- High Knowledge level states a rule unprompted → the payments line "never
  explain policies" was **not** carried over; the prompt says "never do the
  assistant's job for it". A test pins the omission.
- Persistent Persona re-attempts after a refusal → `gave_up` is allowed only
  once the agent has made the Goal impossible **and** the customer "pushed as
  far as your personality would".
- False premise and low Knowledge level (a wrong label for a real fact) →
  "never invent" carries an explicit carve-out: a mistaken belief or wrong
  word the Goal directs is played as written.
- Underspecification withholds, high Knowledge level volunteers → the payments
  line "reveal details only when asked" became "your goal and personality
  decide what you volunteer and when" (Knowledge level does not control
  disclosure timing).
- Pressure Persona → the gate paragraph is verbatim, so its exception applies
  unchanged. Vigilant, out-of-scope drift, channel noise: no instruction
  touches them.

Session 06b re-ran this check when it added the rule statement to a high
Knowledge level customer's knowledge text:
`journey-simulated-user-fidelity-is-a-human-record.md`.

**Episode loop.** A user message is appended to `transcript.jsonl` before
`send_message`; a reply as it arrives. Retrieve, then release, in a `finally`:
both are attempted after every stop reason and after an unexpected exception.
A failed start has no handle, so neither is attempted and a
both-`unavailable` Normalized Trace is written instead. An unexpected
exception (not `AdapterError`, not from the Simulated user) leaves
`episode.json` with `status: aborted`, `stop_reason: null`, and propagates.
Any exception from the Simulated user — not only `LLMError` — is
`simulator_error`.

## Why

- The Transcript is the only place a failed send survives: the adapter's
  record holds acknowledged exchanges only.
- After a request timeout the agent may have finished the Turn server-side;
  the Trace is what counts, so an error is no reason to skip retrieval.
- `release` drops the adapter's fallback record, so the order is not a style
  choice.
- A seventh stop reason for harness bugs would widen a closed set that
  section 8's outcome rules enumerate; `status` keeps the set closed.
- A file that always exists is simpler for `evaluate_episode` than a file
  that may be absent; nothing in the both-`unavailable` Trace is invented.

## What would make us revisit it

- A Persona-fidelity spot-check (none has been run: these instructions are
  designed, not validated) showing the Simulated user stops too early on
  tool-failure Scenarios, invents relative dates, or ignores the carve-out.
- A Journey whose customers must know today's date: add `now` as a grounded
  fact in synthesis rather than special-casing the prompt.
- A high Knowledge level Scenario whose Goal does not spell the rule out: the
  prompt carries no `knowledge_rules` statement, only what the Goal says.
- Parallel execution: the adapter is blocking inside an `async def`.
