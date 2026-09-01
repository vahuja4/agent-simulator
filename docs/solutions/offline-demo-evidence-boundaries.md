---
title: Keep offline demos inside committed evidence boundaries
category: evidence
symptoms:
  - A newer committed gate is chronologically latest but explicitly rejected.
  - A requested coverage cardinality is absent from committed reports.
---

## Question

How should an offline demo choose among committed gate artifacts and present a
requested number that the committed evidence does not establish?

## Decision

Name the selection rule explicitly: use the latest successful full acceptance
gate for success claims, disclose any newer rejected gate, and report an absent
cardinality as not proven. Pin every displayed artifact to a commit and byte
hash, and replay committed completion output instead of regenerating it.

## Why

Chronological recency does not turn rejected calibration evidence into landing
evidence. Likewise, a number in a task description is not evidence when the
current report omits it and the nearest ADR estimate belongs to an older
snapshot. Explicit boundaries keep the demo reproducible and fail closed.

## Revisit when

Revisit the gate selection or cardinality statement when a newer successful
separated-model gate is committed, or when a current report commits a
recomputed pairwise-covering Scenario target.
