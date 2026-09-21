---
title: An aborted Journey synthesis run keeps its evidence and says it was aborted
category: journey-harness
symptoms:
  - The simplify review of scenario_synthesis/journey_synthesis.py found that any exception other than LLMError or Rejection inside the spec loop left a set directory with no provenance.json, and that set id was then refused forever.
  - synthesize_command reported a mid-run ValueError as exit 2, which is documented as "before any network call".
  - tool_failure_conditions skipped the duplicate check and compared orderings as different values; an explicitly empty axis silently meant "everything" (`requested or default`).
  - A Journey listing goal shift or multi-intent turn as supported would have raised KeyError on the first spec that used it, because the generator has no writing direction for them.
  - A grounded date-time with a UTC offset was split at the "+" by the narrative Sealed-world check, so even the stub, which echoes values verbatim, exhausted every spec; a grounded HH:MM:SS was never allowed.
  - parse_narrative raised TypeError when sorting mixed-type extra keys from a Python provider.
---

# An aborted Journey synthesis run keeps its evidence and says it was aborted

## Question

`synthesize_set` creates its set directory and then does fallible work: model
calls, validation, writes. When something unexpected fails part-way, what
should be left on disk, what should the command say, and may the set id be
used again?

## Decision

- Partial evidence is kept. On any unexpected failure after the directory
  exists the run still writes `provenance.json`, with `"status": "aborted"` and
  `"error": {type, message, spec_id}`; counts, specs and accepted hashes
  describe what exists. A normal run writes `"status": "complete"`.
- `synthesize_set` raises `SynthesisAborted` from the original error. It is a
  `RuntimeError`, deliberately not a `ValueError`, so a mid-run `ValueError`
  can never be read as a configuration error. An interrupt is recorded the
  same way and then propagates as itself.
- `synthesize_command` prints one `ABORTED:` line (the message is collapsed to
  one line; `provenance.json` keeps it as raised) and returns 1. Exit 2 means
  an unusable request and only ever happens before the first write — including
  a set directory that appears between the existence check and `mkdir`.
- `verify_provenance` reports an aborted set as a problem.
- The set id stays taken. The user picks a new one; nothing is deleted.
- Everything that can be known before the first write is checked before it:
  duplicate or empty axes, and a supported Complication with no writing
  direction, are `SynthesisConfigError`s from `VariationSettings.resolved`.
  `None` means "every supported value"; `()` never does.
- The narrative check takes a verbatim grounded date-time out whole before it
  tokenizes, and allows its `HH:MM:SS`. Only the exact grounded string is
  removed, so another date, time, offset, code or identifier beside it is
  still rejected, and tests pin that.

## Why

The alternative that frees the set id — build in a staging directory, rename
on success, delete on failure — throws away rejected attempts and accepted
Scenarios that a live run has already paid for, and hides what went wrong. It
is not simpler either. The repository already prefers preserved, attributed
partial evidence over fail-fast cleanup (AGENTS.md, live calibration fan-out).
An aborted set that explains itself costs one set id.

## What would make us revisit it

A resume feature (continue an aborted set's remaining specs) would need the
planned-but-unattempted specs recorded, which `provenance.json` does not list
today. If aborted sets pile up during live generation, the fix is to find the
failure, not to auto-delete. None of this has been exercised by a live run.
