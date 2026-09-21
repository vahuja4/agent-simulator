---
title: Simplify the Journey path once the pipeline exists, and pin its output first
category: scenario-synthesis
symptoms:
  - A /simplify pass over scenario_synthesis/journey_synthesis.py was expected to shrink a 1,061-line file and left it at 1,061.
  - A refactor of the synthesis module had no mechanical proof that saved Scenarios were unchanged.
  - Review of the module surfaced bugs that a behavior-preserving pass must not fix.
---

# Simplify the Journey path once the pipeline exists, and pin its output first

## Question

Should each new module of the Journey-definition path get a `/simplify` pass
as it lands, and how is such a pass shown to be behavior-preserving?

## Decision

One slice ran on 2026-09-21 (`scenario_synthesis/journey_synthesis.py`, commit
`02e5e34`). The remaining slices — `agentsim/journey/` and the sibling
`journey_agent` project — wait until session 09 has landed, and then run as
one pass over the whole path.

A refactor of the synthesis module is checked two ways:
`test_fixed_seed_stub_output_is_pinned_across_code_changes` pins the ordered
Scenario ids of a fixed-seed stub run, and a before/after diff of a `--stub`
set must be empty once `generated_at` and the accepted-file hashes that depend
on it are normalized. Saved YAML is dumped with `sort_keys=False`, so dict
insertion order is part of the bytes; `provenance.json` sorts its keys.

## Why

Four parallel reviewers (reuse, simplification, efficiency, altitude) each
judged the file already clean. Most of its lines are validation, rejection
records and provenance, and removing those is checking less, not simplifying.
The pass improved drift-safety — one `_input_hashes` shared by
`synthesize_set` and `verify_provenance`, one definition of the unqualified
stamp and of the narrative field names — and removed repeated work in
`plan_specs`, without changing the line count. Module-by-module passes cannot
see duplication between modules, which is where the remaining savings are. One
is already known: the bookable-slot rule lives in both
`journey_synthesis._bookable_slots` and `check_against_inputs`.

A Scenario id hashes the set id, the whole planned spec and the narrative, so
pinning the ordered ids pins the plan, the stub narrative and the id
definition in one assertion, independent of timestamps.

## Review findings carried forward, not fixed in the simplify commit

Recorded here because a behavior-preserving commit must not fix them; they are
the scope of session 07c.

- An exception that is neither `LLMError` nor `Rejection` aborts
  `synthesize_set` after the set directory exists and before
  `provenance.json` is written; `_set_directory` then refuses that set id
  forever, and `synthesize_command` reports a mid-run `ValueError` as exit 2,
  documented as "before any network call".
- `tool_failure_conditions` skips the duplicate check the other axes get, and
  `_usage_keys` treats order variants as distinct while derivability compares
  them as sets.
- An explicitly empty axis means "everything" instead of being refused.
- A supported Complication with no `_COMPLICATION_DIRECTION` entry (goal
  shift, multi-intent turn) raises `KeyError` inside the spec loop. Unreachable
  while the appointment Journey marks both unsupported.
- The lexical Sealed-world check rejects a verbatim grounded date-time that
  carries a UTC offset, and never allows `HH:MM:SS`.
- `parse_narrative` raises `TypeError`, not a `malformed-output` Rejection, on
  mixed-type keys from a Python provider.

## What would make us revisit it

A module on this path growing past what one reviewer can hold — then it gets
its own slice early. Or the pinned digest being updated in a commit that
claims to be a refactor: that is the signal the check exists to raise.
