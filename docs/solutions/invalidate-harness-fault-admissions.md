---
title: Invalidate harness-fault admissions append-only
category: scenario-synthesis-lifecycle
symptoms:
  - An admitted Candidate is later rejected by harness revalidation
  - Invalid Qualification evidence still covers a cell or consumes regeneration budget
---

# Question

How should the lifecycle retire an Admission whose evidence was invalidated by a harness defect without rewriting history or blaming the Candidate?

# Decision

Append one `admission-invalidation` event with reason `harness-fault`, archive the admitted library Scenario, and treat the historical Admission as inactive. The cell returns to UNCOVERED and its next Candidate remains ordinal 0. Any ordinary rejection event after an effective Admission is a ledger-validation error.

# Why

Candidate, Qualification, and Admission bundles are immutable evidence. A distinct invalidation preserves that history and the human ruling while preventing contradictory active state and keeping harness failures outside the K regeneration budget.

# Revisit

Revisit if the lifecycle gains a general event store with first-class supersession, or if non-harness Admission withdrawals need different budget or reporting semantics.
