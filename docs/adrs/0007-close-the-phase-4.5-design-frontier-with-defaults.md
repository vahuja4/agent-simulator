# Close the Phase 4.5 design frontier with defaults

The remaining Phase 4.5 design frontier closes with the following defaults.
Detailed schema, placement, reporting format, and lifecycle mechanics remain
specification work rather than open design decisions.

## Fitness-target mapping

Use the direct structured contracts already established by the prototype and
Phase 4 acceptance data: D1 same-turn is `assertion:validated_submit`, D1 at
the gate is `judge:explicit_confirmation`, D2 is
`assertion:refetch_after_card_switch`, D3 is `judge:honest_failure`, D4 is
`judge:warning_acknowledged`, D5 is `judge:card_disambiguation`, D6 is
`judge:journey_scoping`, and D7 is `judge:external_account_caveat`. D1's two
shapes are separate fitness obligations; a Scenario is admitted to the shape
it proves. Code owns the Coverage-cell structure, target, and Fixture bindings;
an LLM may realize narrative surface fields but may neither alter that semantic
structure nor invent facts.

A cell with no applicable known defect may be admitted by defects-off precision
alone: 3/3 passes under the existing compliance requirements. Its provenance is
marked **detection-unproven**, so admission does not imply defect-detection
evidence. **Revisit trigger:** introduction of coverage-guided generation,
which must re-evaluate detection-unproven cells without hiding their original
denominator or provenance.

## Multi-simulator fitness

Use Luna alone for admission. Simulator diversity is a future robustness tier,
not admission evidence. **Revisit trigger:** the Phase 5 simulator-family
migration; that decision must also define whether and how existing fitness
records require re-qualification after a simulator change.

## Repetition and seed semantics

N=3 identifies a Scenario x configuration observation, not an intrinsic
Scenario property. Record model identifiers, prompt hashes, and Fixture version
for every run, and accept simulator stochasticity as the source of variance;
add no further seed-control mechanism. **Revisit trigger:** observed
qualification instability under an unchanged recorded configuration.

## Near-duplicate control and library budget

Admit at most two Same-cell-equivalent Scenarios. The initial library target is
the eligible-cell count—one admitted Scenario per eligible cell—and v1 has no
pruning mechanism. **Revisit trigger:** the synthesized library exceeds roughly
100 Scenarios or reporting demonstrates material redundancy.

## Phase 4.5 acceptance gate

Phase 4.5 is complete only when: the ADR 0004 eligibility reconciliation is
complete; at least one synthesized Scenario is admitted for each of goal shift,
multi-intent turn, out-of-scope drift, and channel noise after its definition
test passes; every admitted Scenario holds its applicable fitness contract; the
append-only rejection ledger and a coverage report separating covered,
BLOCKED, UNCOVERED, and regeneration-exhausted obligations are produced; and
the curated suite remains green. **Revisit trigger:** a prerequisite coverage,
taxonomy, eligibility, or fitness ADR is superseded before the gate executes.
