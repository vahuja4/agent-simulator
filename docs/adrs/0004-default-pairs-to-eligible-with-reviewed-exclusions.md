# Default pairs to eligible with reviewed exclusions

Every cross-axis pair is eligible by default. A pair may be excluded only under
one of four closed reason codes: contradiction between approved value contracts,
impossibility under the approved journey graph, impossibility in the fixture
domain, or non-applicability under an approved axis contract, including the
D1–D7 fitness mapping. Cost, low expected value, generator or model limitations,
and missing implementation are not exclusion reasons.

Eligible gaps have two non-pooled states. **BLOCKED** means the current
implementation or generator cannot realize the obligation for a recorded
reason; it is engineering debt expected to trend to zero. **UNCOVERED** means
the obligation is realizable but no Scenario has been admitted; it is pipeline
backlog. An exhausted fitness-regeneration budget therefore leaves an obligation
UNCOVERED rather than excluded.

The reviewed exclusion artifact records each pair, its reason code, rationale,
and evidence. Coverage reports bind to the artifact's version or content hash.
Any change that reduces coverage obligations requires explicit review. Entries
affected by a changed taxonomy, journey graph, fixture domain, or fitness-target
mapping must be re-reviewed. Artifact ownership and location are deferred to the
Phase 4.5 specification.

Before Phase 4.5 makes any acceptance-gate coverage claim, the prototype's
generator-derived eligibility must be reconciled against this contract. Every
pair that the current J1-graph-driven implementation cannot produce, including
pairs lost through skipped validation failures, must be classified as excluded
under one of the four codes, BLOCKED with a stated reason, or eligible and owed.

This rejects an explicit allowlist because omissions could silently erase
obligations, and rejects generator-derived eligibility because implementation
limits must not define the claimed coverage universe.
