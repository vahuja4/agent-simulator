---
title: Slice 3 keeps offline lifecycle evidence immutable and resumable
category: architecture
symptoms:
  - Realization retries could accidentally consume candidate replacement budget.
  - Interrupted admission could leave evidence that cannot be resumed safely.
  - Stub qualification could pass without proving every required check ran.
---

# Question

How should Slice 3 exercise production and qualification completely offline
while preserving the approved candidate, evidence, and admission contracts?

# Decision

Use injected stub provider and `run_scenario`-shaped runner protocols that never
construct clients. Keep realization attempts separate from candidate ordinals,
record every episode and required check explicitly, hash-link rejection
evidence, derive candidate identity from Blueprint + ordinal + normalized
Scenario, and make terminal transitions resumable around atomic file writes.
Qualification stores the repository Transcript as canonical JSONL and binds
separate Trace, Assertion-result, and Judge-ruling artifacts by path and hash.
Candidate production validates a hidden staging bundle before its atomic
rename; stale partial bundles are quarantined and verified complete bundles
are reused idempotently.
Admission derives repetition counts, Fitness configuration, and defect toggles
from the current configuration, Candidate, and reviewed contracts rather than
trusting evidence-declared values. Assertion results and Judge rulings require
exact IDs, boolean outcomes, and agreement with structured failures.

# Why

This makes all N=3 and K=2 branches testable offline, prevents missing or
degraded checks from becoming evidence, preserves rejected artifacts, and lets
an interrupted command finish without moving files already referenced by the
ledger. Recursive admission validation prevents a valid outer record from
hiding missing, extra, mismatched, or non-contract nested evidence.

# What would make us revisit it

Revisit when Slice 4 introduces a live realization provider, when Slice 5 wires
the real qualification runner, or if durable evidence moves to the approved
external-retention form. The admission rules and identities remain unchanged.
