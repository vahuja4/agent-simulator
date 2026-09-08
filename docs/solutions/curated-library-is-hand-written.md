---
title: The curated library is the hand-written set
category: scenario-synthesis
symptoms:
  - Two pipeline-synthesized Scenarios were committed under scenarios/ and failed the curated loader on every run.
  - The reviewed persona-archetypes contract was edited to map them as curated, changing reviewed hashes.
  - Fourteen tests, including all offline coverage of run_calibration.py, stayed red for six days behind a stale baseline.
---

# The curated library is the hand-written set

## Question

When a Scenario with synthesis provenance appears under `scenarios/` and the
persona-archetypes contract's curated-mapping check demands a mapping for it,
which side is wrong?

## Decision

The file placement is wrong, never the contract. `scenarios/` holds exactly the
reviewed hand-authored Scenarios (13 as of 2026-09-08). Synthesized output lives
under the synthesis output root with its Candidate bundle. The two generated
Scenarios were deleted with their mapping rows, which returned
`persona-archetypes.yaml`, `pair-exclusions.yaml`, and the mapping report to
their byte-identical pre-`c0c0860` reviewed state.

Consequence accepted: the four live qualification bundles recorded on
2026-09-02 were produced under the `c0c0860` hashes and now validate as stale.
Reported coverage was already zero covered cells with stale evidence at main
HEAD, so no claim changed.

## Why

The curated loader fails closed on synthesis provenance by design, and the
compliance-gate denominator and the library lint test both pin the curated
count. Editing a reviewed contract to absorb a misplaced file silently changes
every hash downstream of it and invalidates admitted evidence, which is a far
larger change than moving a file. The contract's bijection check did its job;
the fix that followed it was aimed at the wrong side.

## What would make us revisit it

If a synthesized Scenario is deliberately promoted into the curated library, do
it as an explicit reviewed change: strip the provenance, add the mapping row and
report entry, update the embedded dependency hashes, and re-qualify affected
admissions in the same phase. Never as a side effect of a calibration commit.
