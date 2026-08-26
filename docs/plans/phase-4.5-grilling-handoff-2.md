# Phase 4.5 scenario-synthesis grilling handoff 2

## Purpose

Resume the Phase 4.5 design grill after closure of the Complication taxonomy.
This is still a grilling session, not a specification or implementation-planning
session. Work one area at a time, present concrete options with trade-offs and a
recommendation, and record each settled decision before moving on. Stop when the
triaged frontier is empty.

## Start here

Read, in order:

1. `AGENTS.md` and `CONTEXT.md`.
2. `plans/phase-3-baseline.md`, `plans/phase-4-build.md`, and
   `plans/phase-4-handoff.md`.
3. `docs/solutions/simulator-model-luna.md`.
4. `.agents/skills/grill-with-docs/SKILL.md`, then its required `grilling` and
   `domain-modeling` skills.
5. `docs/plans/phase-4.5-grilling-handoff.md`.
6. ADRs 0001–0007 under `docs/adrs/`.
7. `docs/reports/persona-archetype-mapping.md` and
   `docs/reports/complication-taxonomy-mapping.md`.

Do not browse old calibration transcripts unless a later question makes them
necessary. The committed `scenario_synthesis/` package is a prototype to audit,
not the Phase 4.5 specification.

## Settled — do not relitigate

### Areas 1–5

The baseline, constrained-interaction coverage model, Persona taxonomy,
Knowledge-level independence and Sealed-world rule, and two-sided fitness
admission contract are recorded in the first handoff and ADRs 0001–0003.

Area 5 is now fully closed. A cell receives an initial fitness candidate plus
at most **K=2** fresh replacements after completed fitness rejection. This is
separate from each candidate's realization-format retry. Three rejected
candidates leave the cell **UNCOVERED—regeneration exhausted**; exhaustion is
not an eligibility exclusion. More attempts require a reviewed factory repair,
and prior rejection history remains append-only.

### Pair eligibility

Pairs are eligible by default. The exclusion list has exactly four reason
codes: approved-contract contradiction, journey-graph impossibility,
fixture-domain impossibility, and approved-axis non-applicability. Cost, low
expected value, generator/model limits, and missing implementation cannot
exclude a pair.

Eligible gaps are non-pooled: **BLOCKED** means current implementation or
generator debt prevents realization for a stated reason; **UNCOVERED** means
the obligation is realizable but lacks an admitted Scenario. Coverage reports
bind to the exclusion artifact's version/hash. Coverage-reducing changes require
explicit review, with re-review on relevant taxonomy, graph, fixture, or fitness
mapping changes.

Before any Phase 4.5 acceptance coverage claim, reconcile every pair the
prototype cannot emit as excluded-with-code, BLOCKED-with-reason, or eligible
and owed. See ADR 0004.

### Complication taxonomy

The closed nine-value axis is: none, underspecification, mid-conversation
correction, goal shift, multi-intent turn, false premise, out-of-scope drift,
channel noise, and ambiguous reference. Applicability uses a reviewed
precondition matrix under the same version/hash and coverage-reduction review
contract as pair exclusions. False premise requires a real fixture fact about
which the user holds an actual incorrect belief.

Procedure branches, validation outcomes, tool failures, and fixture conditions
are not conversational Complications. In particular,
`j3-below-minimum-fixed-autopay` is none; its warning is a journey/fixture
condition. `j5-cancel-autopay-pending` is false premise. Ambiguous reference is
distinct from underspecification because it tests disambiguation rather than
elicitation.

The curated distribution is 9 none / 4 non-none. Goal shift, multi-intent turn,
out-of-scope drift, and channel noise have zero curated instances. They are
**designed, not yet empirically validated**: the first synthesized realization
of each is also a definition test, and ambiguity requires a boundary ruling
before admission. This distribution is required input to the later
near-duplicate/library-budget decision. See ADR 0005 and the complication
mapping report.

### Knowledge-level behavior

Use the relevant-fluency ladder with symmetric observable evidence. Low
exhibits at least one material fluency gap; medium states Goal-relevant facts
correctly and visibly relies on the agent for at least one procedural rule or
consequence; high makes at least one correct unprompted statement of a relevant
rule or consequence. Simulator compliance checks the selected level on every
fitness repetition, and identical behavior cannot earn multiple level credits.

Knowledge changes fluency, not fact availability, disclosure timing, Persona,
or Complication behavior. The Sealed-world rule applies at every level.
Knowledge and false premise are orthogonal, so high knowledge x false premise
is eligible and valuable. Pairings are default-eligible; non-applicability
requires the absence of a real, behaviorally distinguishable referent, while
missing generator support is BLOCKED.

The first low-level realization is also a judge-robustness test because the
calibrated criteria have not seen wrong-label Personas. Low level is therefore
designed but not yet empirically validated; judge instability becomes an
N-series entry handled through the calibration-gated process. See ADR 0006.

## Frontier closed

The remaining five areas closed by explicit default on 2026-08-26. ADR 0007
records the direct D1–D7 fitness mapping and detection-unproven admission,
Luna-only admission, Scenario x configuration repetition semantics, the
two-per-cell and initial one-per-eligible-cell library budget, and the precise
Phase 4.5 acceptance gate. Each decision has a named revisit trigger.

The grilling frontier is empty. Specification writing is a separate session;
use `docs/plans/phase-4.5-spec-input.md` as its consolidated input.

## Deferred to specification

Provenance/schema field details, reporting formats, configuration ownership and
locations, operational bounds, and candidate-lifecycle mechanics are not part
of this grill. Ask at most one question for any of these only if a genuine
design fork appears; otherwise record **spec-level, no contested decision** and
move on. Ownership and placement of the exclusion and applicability artifacts
are already explicitly deferred.

## Recorded follow-up — do not act now

Fix the `j1-happy-path` Persona contradiction found in the Persona mapping
report. The committed Scenario YAML edit is approval-gated and must be bundled
atomically with the authoritative taxonomy-artifact commit. Do not perform it
during grilling.

## Working-tree and safety state

The grilling docs and `CONTEXT.md` changes are uncommitted. Preserve all prior
user changes and the unrelated untracked `.pptx` files. No Scenario YAML,
judge criterion, mock behavior, or live LLM run was changed or invoked during
this session.
