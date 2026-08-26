---
title: Phase 4.5 synthesis coverage contract
category: architecture
symptoms:
  - Generator limitations could silently shrink claimed pair coverage.
  - Conversational difficulty was conflated with journey and fixture conditions.
  - Repeated candidate rejection had no terminal coverage state.
  - Synthesized admission lacked closed Knowledge, fitness, and library contracts.
---

# Question

What design contract must Phase 4.5 scenario synthesis satisfy before its
specification can define schemas and mechanics?

# Decision

Use constrained interaction Coverage cells, reviewed behavioral taxonomies,
default-eligible pairs with four exclusion reasons, and separate BLOCKED from
UNCOVERED. Limit each cell to an initial candidate plus K=2 post-fitness
replacements under strict N=3 qualification. Use the relevant-fluency Knowledge
ladder and closed nine-value Complication taxonomy. Admit detection-unproven
cells through 3/3 defects-off precision when no known defect applies. Luna alone
supplies admission evidence; N=3 identifies Scenario x configuration. Cap
Same-cell-equivalent admissions at two and initially target one Scenario per
eligible cell. ADRs 0001–0007 and `docs/plans/phase-4.5-spec-input.md` are the
authoritative decision index.

# Why

This makes the coverage denominator reviewable, prevents implementation limits
from erasing obligations, separates engineering debt from synthesis backlog,
and stops brute-force search. Observable Knowledge evidence and single-axis
Complications prevent cosmetic variants from earning semantic coverage, while
detection-unproven provenance permits useful precision controls without
overclaiming defect sensitivity.

# Revisit when

Revisit the relevant section only at its ADR trigger: changed source contracts,
coverage-guidance introduction, the Phase 5 simulator migration, unchanged-
configuration qualification instability, a library above roughly 100 or
reported redundancy, or supersession of a gate prerequisite. First realizations
of unvalidated Complications and low Knowledge remain explicit definition or
judge-robustness tests rather than implicit reasons to reopen the whole design.
