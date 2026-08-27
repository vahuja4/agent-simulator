---
title: Phase 4.5 reporting and completion evidence
category: architecture
symptoms:
  - Coverage claims could be inferred from files without validating admission evidence.
  - Markdown reports could diverge from the machine-readable coverage record.
  - Phase completion could be reported without clause-specific evidence.
---

# Question

How should Slice 4 report current synthesis coverage and evaluate the Phase 4.5
completion claim without consulting Historical quarantine or trusting stale state?

# Decision

Build `coverage.json` from the current reviewed obligation inventory and persisted
Candidate, Qualification, library, and Rejection ledger state. Treat it as the
authoritative record and render `coverage.md` as a pure deterministic projection.
An admission covers obligations only after its identity, complete Qualification,
evidence hashes, library bytes, configuration, and reviewed contract hashes validate.
Keep eligible pairs as the acceptance-gate unit, eligible cells as the reporting
denominator, and regeneration exhaustion as an explicit attribute of UNCOVERED cells.
The completion evaluator fails clause 4 while any eligible pair is BLOCKED or
UNCOVERED and summarizes those counts without treating excluded pairs as debt.
Markdown reports show status counts per obligation kind and must byte-equal the
projection of the authoritative JSON before they count as completion evidence.

Evaluate the five completion clauses separately. Definition tests, a replacement
eligibility-reconciliation artifact, and curated-suite greenness require explicit
hashed evidence. The committed Slice 2 reconciliation is usable evidence only while
its reviewed contract hashes remain current. Missing, mismatched, or stale evidence
produces a named gap; it never receives optimistic credit.
Definition-test evidence binds the admitted Candidate ID, ordinal-zero production
identity, and a contained evidence hash. Absolute paths, parent traversal, stale
Rejection-ledger contract hashes, and later Candidate ordinals fail closed.

# Why

This binds every covered claim to the evidence that admitted the synthesized
Scenario, prevents generator reachability or legacy output from shrinking the
coverage universe, and makes the human report mechanically consistent with the JSON
record. Clause-level results keep independent prerequisites visible even when the
overall completion claim fails.

# What would make us revisit it

Revisit the evidence bindings if a reviewed synthesis contract changes its identity
or lifecycle schema, if Phase 5 defines a different persisted live-run bundle, or if
an ADR supersedes the pairwise acceptance unit, cell denominator, or completion
clauses. Do not relax fail-closed validation merely because evidence is unavailable.
