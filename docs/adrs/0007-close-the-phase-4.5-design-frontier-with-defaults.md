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

### Amendment — 2026-08-26: use a pairwise-covering admission target

The revisit trigger fired when the first Slice 2 plan enumerated 4,092 eligible
J1 cells. Replace the one-admitted-Scenario-per-eligible-cell target with a
pairwise-covering set: every eligible pair of Coverage-cell axis values must
appear in at least one admitted Scenario. Eligible cells remain the reporting
denominator, while pair obligations are the acceptance-gate coverage unit,
consistent with ADR 0002. Excluded pairs do not enter the target; BLOCKED pairs
remain eligible engineering debt and prevent completion until they become
coverable. The cap of two Same-cell-equivalent Scenarios and K=2 regeneration
limit are unchanged.

For the contracts current at `b8cf29c`, a deterministic greedy set-cover
estimate selects 42 Scenarios from the 3,060 unblocked J1 cells to cover all 283
currently realizable J1 pair obligations. At each step the estimate selects the
cell covering the most uncovered pair obligations, with canonical `cell_id` as
the deterministic tie-breaker, and stops when no realizable pair remains. The
full pair denominator is 406: the other 123 pair obligations are BLOCKED and
cannot be covered by an admitted Scenario in the current plan. This is a
planning estimate rather than a proof of minimum cardinality and must be
recomputed when reviewed contracts or graph semantics change.

## Phase 4.5 acceptance gate

Phase 4.5 is complete only when: the ADR 0004 eligibility reconciliation is
complete; at least one synthesized Scenario is admitted for each of goal shift,
multi-intent turn, out-of-scope drift, and channel noise after its definition
test passes; every admitted Scenario holds its applicable fitness contract; the
append-only rejection ledger and a coverage report separating covered,
BLOCKED, UNCOVERED, and regeneration-exhausted obligations are produced; and
the curated suite remains green. **Revisit trigger:** a prerequisite coverage,
taxonomy, eligibility, or fitness ADR is superseded before the gate executes.
