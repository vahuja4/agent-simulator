---
title: Journey synthesis — code owns structure, the model writes three fields, validation is not Qualification
category: journey-harness
symptoms:
  - Session 03 left knowledge_evidence.kind as a free string, so two files could claim the same Knowledge level with different, unverifiable evidence.
  - A model asked for expected outcomes or checks can return plausible ones that disagree with the Journey definition, and "override it" hides that it happened.
  - A deterministic stub that rendered grounded-fact paths into its narrative failed its own Sealed-world check, because a path holds Fixture ids no customer knows.
  - A false-premise or mid-conversation-correction narrative needs a wrong or superseded value, which the Sealed-world check rejects unless that value is itself a real Fixture fact.
---

# Journey synthesis — code owns structure, the model writes three fields, validation is not Qualification

## Question

`scenario_synthesis/journey_synthesis.py` generates Scenarios for a Journey
outside payments from two authoritative inputs. What may the model decide,
what happens when it oversteps, how is Knowledge-level evidence kept from
meaning anything an author likes, and what does "validated" allow anyone to
claim?

## Decision

- The model writes `description`, `persona.traits` and `goal`. Everything else
  — Fixture bindings, archetype, Knowledge level and evidence, Complication,
  grounded facts, max Turns — is planned by code, and `expected_outcome` and
  `criteria` are derived from `journey.yaml`. A response carrying any other
  field is rejected with `model-supplied-derived-field`, **even when the value
  agrees** with what code derives. It is never overridden.
- The model is never shown `tool_failures`, the expected outcome or the
  checks. A customer knows none of them, and a narrative written with them in
  view leaks the test into the Persona.
- `knowledge_evidence.kind` is closed and one-to-one with Knowledge level
  (`material_fluency_gap` / `relies_on_agent_for_rule` /
  `states_rule_unprompted`, the Phase 4.5 names, pinned equal by a test). A
  `rule` is a `journey.yaml` `knowledge_rules` id; a `referent` must be the
  path of one of the Scenario's own grounded facts. The loader enforces all of
  it, so a hand-edited file cannot drift either.
- A Complication that needs a wrong or superseded value takes it from real
  Fixture state and adds it to `grounded_facts`: the false-premise believed
  value is another real provider; the first-requested slot of a correction is
  another bookable slot. A combination whose Fixture precondition is missing
  (ambiguous reference without a second matching appointment) is not planned.
- Validation reuses the session-03 seam on the exact text to be saved
  (`load_journey_scenario`, `check_against_inputs`) and adds only the narrative
  Sealed-world check. That check is lexical: digit-bearing tokens and month or
  weekday names must come from a grounded fact. It can reject honest text and
  cannot prove a sentence true.
- `fixture_state_sha256` is the canonical-JSON hash (`FixtureState.sha256`),
  the value the agent service returns and the Normalized Trace records;
  `journey_sha256` is the file's byte hash. `verify_provenance` re-checks both.
- Planning takes the least-used value of every axis first, ties broken by one
  seeded shuffle. Lock-step indexing pairs same-length axes permanently.
- Grounded-fact **paths** are never rendered into text a model or a Simulated
  user reads; only values are. Session 05's knowledge text must do the same.

## Why

Rejecting an agreeing derived field looks pedantic, but overriding makes the
saved file correct while hiding that the model tried to author an outcome; the
next prompt change would turn the silent disagreement into a silently wrong
test. One kind per level is ADR 0006's "identical behavior can never earn
credit for more than one level" made checkable. Drawing wrong values from
Fixture state is the CONTEXT.md definition of false premise — an incorrect
belief about real Fixture state, never an invented fact — and it is also what
lets one Sealed-world check cover every Complication without exemptions.

## What would make us revisit it

Live generation rejecting a large share of honest narratives (counts written
as digits, relative dates such as "tomorrow") would justify a smarter
narrative check, not a looser one. A Journey whose Knowledge evidence cannot
be expressed as a rule id or a grounded-fact path would reopen the kind set.
None of this has been run against a model, no synthesized Scenario has been
run in an Episode, and ADR 0006 Simulator compliance is not checked anywhere
on this path: passing validation establishes nothing about test quality,
coverage, Qualification or Admission.
