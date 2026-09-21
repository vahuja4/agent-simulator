---
title: Simulated-user fidelity is a human Spot-check record, not an automated check; a high Knowledge level customer is shown its rule
category: journey-harness
symptoms:
  - A Scenario whose knowledge_evidence.kind is states_rule_unprompted worked only if its model-written Goal happened to spell the rule out; the stub's Goal never does.
  - The Simulated user's prompt said "this is ALL you know" while the rule it was to state was nowhere in it.
  - A later session proposes lexical matching, a self-report field, deviation flags or a fidelity Judge for the Simulated user.
  - The Persona-fidelity spot-check AGENTS.md requires had no place to be written down, so its labels would evaporate.
---

# Simulated-user fidelity is a human Spot-check record, not an automated check

## Question

Nothing on the Journey-definition path checks whether the Simulated user
played the Scenario it was given (ADR 0006 Simulator compliance is not ported;
design note section 12 item 3). Session 05b then found a concrete gap: a high
Knowledge level customer is never shown the rule it must state. Should fidelity
be checked automatically, and how does the rule reach the customer?

## Decision

- **No automated check of Simulated-user behavior.** Considered on 2026-09-21
  and rejected by the user: lexical matching of the customer's messages, a
  self-report field in its structured answer, deviation flags, a fidelity
  Judge. Session 06b added none.
- **Fidelity is a human ruling, kept as data.** `agentsim/journey/spot_check.py`
  defines the Spot-check record — run id, scenario id, reviewer, date, and
  `faithful | drifted | not_applicable` plus a note for each of Persona,
  Knowledge level, Complication and grounded facts — in YAML files under
  `journey_spot_checks/`, with a strict loader
  (`load_spot_check_records(path, *, runs_root)`) and a validate-only command.
  Unknown fields, unknown verdicts, a `drifted` verdict with no note, a
  duplicate record and a reference to an Episode that does not exist (or to a
  Scenario with two Episodes in the Run) are refused. Run and scenario ids are
  compared with what is on disk, never joined into a path.
- **The rule statement is permitted knowledge for one evidence kind only.**
  `render_journey_knowledge(scenario, journey)` appends the statement of
  `knowledge_evidence.rule` under "A rule you know about how this works:" for
  `states_rule_unprompted`; never for `relies_on_agent_for_rule` (that customer
  depends on the agent for it) or `material_fluency_gap`; never the rule's id.
- **Construction takes the Journey definition.**
  `JourneySimulatedUser.for_scenario(llm, scenario, journey, *, model=None)` —
  `journey` replaces `agent_role=`. `live_simulated_user(scenario, journey,
  model=None)` is unchanged. A rule the definition does not define raises
  `JourneyDefinitionError` (`JourneyDefinition.knowledge_rule`) at build time,
  for either rule-bearing kind — never a customer quietly built without it.

## Why

An LLM customer's free text defeats keyword matching (negation, paraphrase,
repeating what the agent offered); a self-report is the same model labelling
itself; a fidelity Judge has nothing to be tuned against. Each would raise
false alarms costing more attention than it saves, and a quiet check would be
read as evidence it is not. Deterministic checks stay right where the evidence
is structured (Assertions over the Normalized Trace, provenance hashes). A
strict record format is what turns today's required spot-check into tomorrow's
labelled data.

The rule is a represented domain rule, which the Sealed-world rule already
lets a customer know; it is not a criterion, so showing it leaks nothing about
evaluation. The definition is passed whole rather than as `knowledge_rules`
because construction already needed `agent_role` from it: one argument, and
tests pin that nothing else of it reaches the prompt (criterion ids and
statements, outcome ids, `tool_failures`, fact paths, Fixture ids, rule ids —
for all three kinds).

**Persona-conflict check (AGENTS.md; re-run 2026-09-21 for this instruction
change, by reading the new knowledge section against the four archetype, three
Knowledge-level and seven supported Complication directions in
`scenario_synthesis/journey_synthesis.py`):**

- High Knowledge level "correctly states the named rule without being
  prompted" → now possible without breaking "this is ALL you know — never
  invent": the change removes a latent conflict rather than adding one.
- Medium "visibly relies on the agent for the named rule" → would conflict if
  shown the rule; it is not, and a test pins it. Low names no rule.
- The heading states knowledge and gives no instruction to say it, so it does
  not fight underspecification (withholds *required facts*; a rule is not one)
  or "Knowledge level does not control disclosure timing" — the Goal still
  decides what is volunteered and when.
- False premise at high Knowledge level: a general rule (e.g. a slot belongs to
  one provider) does not contradict a mistaken belief about one real fact; the
  carve-out for a mistaken belief is unchanged.
- Pressure, vigilant, persistent, cooperative; correction, drift, noise,
  ambiguous reference: no text they depend on changed. Both confirmation-gate
  texts are still pinned byte-equal to `agentsim/simulator.py`, which was not
  edited; 05b's decision about dates is untouched.

This is a reading, not a run: no Persona-fidelity spot-check has been made of
these instructions. One thing to watch in the first live Run: the knowledge
text is repeated in the per-turn reminder, so a high Knowledge level customer
may restate the rule more often than a person would.

## What would make us revisit it

- Enough Spot-check records exist to tune and measure a fidelity Judge (or an
  RLM-style cross-Run audit) — the only route back to automation.
- Spot-check records show high Knowledge level customers parroting the rule
  every Turn: move the rule out of the per-turn reminder.
- A Knowledge-level kind is added or changes meaning (`KNOWLEDGE_EVIDENCE`):
  decide again which kinds know the rule.
- A second Journey's knowledge rules are not things a customer could plausibly
  know: the "permitted knowledge" reading needs review.
