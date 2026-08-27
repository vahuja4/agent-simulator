# Phase 4.5 scenario-synthesis specification input

## Purpose and boundary

This document is the consolidated input to a later Phase 4.5 specification
session. The design grill is closed. This is not the specification and does not
choose deferred field names, file locations, report layouts, lifecycle
mechanics, operational limits, or implementation steps.

Phase 4.5 grows coverage beyond hand-authored YAML by qualifying synthesized
Scenarios through the existing Scenario schema and batch machinery. Combination
structure is reviewed and code-defined. An LLM may realize narrative surface
fields but may not choose Coverage-cell axes, alter Fixture bindings or Fitness
targets, or invent facts.

## Settled design decisions

1. **Prototype baseline — ADR 0001.** Audit and productize the committed
   `scenario_synthesis/` prototype. Historical candidates remain quarantined
   and receive no fitness credit.
2. **Coverage model — ADR 0002.** Use constrained interaction coverage over
   journey path, Persona archetype, Knowledge level, Complication,
   fixture-state equivalence class, and Fitness target. Require eligible values
   and pairs plus journey-edge and known-defect coverage; do not universally
   require the Cartesian product.
3. **Behavioral taxonomy — ADR 0003.** Use exactly one of Cooperative,
   Pressure, Vigilant, or Persistent per Scenario. Knowledge is independent.
   Synthesized Scenarios contain zero or one non-none Complication.
4. **Fitness admission and regeneration — grilling handoffs 1–2.** A candidate
   must pass simulator compliance and the strict two-sided N=3 contract: 3/3
   defects-off passes, and 3/3 exact expected structured failures with only its
   target defect enabled and no unrelated failure. Errors, degradation, and
   incomplete outcomes provide no evidence. Each cell gets an initial candidate
   plus K=2 post-fitness replacements; exhaustion leaves it UNCOVERED and its
   rejection history append-only. Repair the shared factory, never a rejected
   candidate.
5. **Eligibility — ADR 0004.** Pairs are eligible by default. The only exclusion
   reasons are approved-contract contradiction, journey-graph impossibility,
   fixture-domain impossibility, and approved-axis non-applicability. BLOCKED
   and UNCOVERED remain separate, and reports bind to reviewed exclusion and
   applicability artifact versions or hashes.
6. **Complications — ADR 0005.** The closed axis is none,
   underspecification, mid-conversation correction, goal shift, multi-intent
   turn, false premise, out-of-scope drift, channel noise, and ambiguous
   reference. Applicability uses a reviewed precondition matrix.
7. **Knowledge — ADR 0006.** Use symmetric observable relevant-fluency
   evidence: low exhibits a material gap; medium states correct Goal-relevant
   facts and visibly relies on the agent for a rule or consequence; high makes
   a correct unprompted statement of a relevant rule or consequence. Knowledge
   does not control disclosure, and false premise is orthogonal to level.
8. **Closing defaults — ADR 0007.** Use the fitness mapping, simulator policy,
   repetition semantics, library budget, and completion gate below.

## Closing defaults

### Fitness targets and realization boundary

| Target shape | Required structured failure |
|---|---|
| D1 same-turn | `assertion:validated_submit` |
| D1 at-the-gate | `judge:explicit_confirmation` |
| D2 | `assertion:refetch_after_card_switch` |
| D3 | `judge:honest_failure` |
| D4 | `judge:warning_acknowledged` |
| D5 | `judge:card_disambiguation` |
| D6 | `judge:journey_scoping` |
| D7 | `judge:external_account_caveat` |

D1's shapes are separate obligations. Cells with no applicable known defect
may qualify through 3/3 defects-off precision and simulator compliance alone,
with **detection-unproven** provenance. Coverage-guided generation is deferred;
when introduced, it must revisit these cells without obscuring the denominator
or their original evidence.

### Simulator and repetitions

Luna alone supplies admission evidence. Diversity is a later robustness tier.
Phase 5's required simulator-family migration must decide re-qualification of
existing records. N=3 identifies Scenario x configuration; every run records
model identifiers, prompt hashes, and Fixture version. Simulator stochasticity
is accepted without another seed-control mechanism.

### Library budget

Same-cell cap: two admitted Scenarios. Initial target: one admitted Scenario per
eligible cell, so the target count equals the eligible-cell count. V1 has no
pruning mechanism. Revisit when the synthesized library exceeds roughly 100 or
reports show material redundancy. The curated 9 none / 4 non-none distribution
is the baseline against which synthesis expansion is reported.

## Phase 4.5 completion claim

Phase 4.5 is complete only when all five conditions hold:

1. Every prototype-unemittable pair is reconciled as excluded with an ADR 0004
   reason, BLOCKED with a reason, or eligible and owed.
2. At least one synthesized Scenario is admitted for each currently unpopulated
   Complication: goal shift, multi-intent turn, out-of-scope drift, and channel
   noise. Each first realization passes its definition test.
3. Every admitted synthesized Scenario holds its applicable fitness contract.
4. The append-only rejection ledger and a coverage report separating covered,
   BLOCKED, UNCOVERED, and regeneration-exhausted obligations are produced.
5. The curated suite remains green.

## Specification-level work with no contested design decision

The specification must define provenance/schema fields, artifact ownership and
locations, reporting formats, configuration placement, operational bounds, and
candidate-lifecycle mechanics. These are deferred mechanics, not invitations to
reopen the ADR decisions. In particular, it must preserve generated-versus-
curated identity, configuration snapshots, reviewed artifact hashes, rejection
history, and detection-unproven status.

## Recorded follow-ups

- **Contract-precondition evidence.** Validate contract preconditions against
  the governing ADR definition; a single curated exemplar is not authoritative
  evidence of the full precondition.
- **Slice 5C pilot-review format.** Use the pair-exclusion review page's
  per-entry evidence plus explicit review-question format as the template for
  the Slice 5C pilot review.
- **Mock-findings worked example.** Use the M-002 arc—bounded probe finding,
  mock-findings ledger entry, approval-gated fix, and regression guard—as the
  worked example of the mock-findings process.
- **Pre-Slice-5 J1 graph semantics.** Resolve and review J1 graph semantics for
  `goal-shift` and `multi-intent-turn` before Slice 5 begins.
- **`j1-happy-path` Persona correction.** The curated YAML contradicts its
  everything-upfront Goal by saying the Persona answers one question at a time.
  Its explicitly approved correction must be atomic with the authoritative
  taxonomy-artifact commit; do not silently mutate the Scenario.
- **Four unvalidated Complications.** Goal shift, multi-intent turn,
  out-of-scope drift, and channel noise are designed but not yet empirically
  validated. Their first admitted realizations are definition tests requiring
  explicit boundary rulings for any ambiguity.
- **Low-knowledge judge exposure.** Wrong-label Personas are new inputs to
  judge criteria calibrated on correct-term Personas. The first low-level
  realizations are judge-robustness tests; instability becomes an N-series entry
  resolved through the approval- and live-verification-gated calibration
  process.
- **Phase 5 simulator migration.** The cross-family simulator change must
  preserve judge/simulator family separation for reported runs, perform the
  required Persona-fidelity spot-check, and define fitness-record
  re-qualification after the simulator changes.
