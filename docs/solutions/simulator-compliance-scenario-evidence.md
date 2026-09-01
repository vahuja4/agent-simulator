---
title: Supply governing Scenario evidence to simulator compliance
category: architecture
symptoms:
  - Grounded customer claims fail when the assistant never repeats them.
  - Curated calibration and production Qualification build different Judge inputs.
---

# Question

How should simulator compliance receive the Scenario Goal, supplied knowledge,
declared Complication, and `goal_facts` without changing criterion wording or
invalidating the ordinary Judge contract?

# Decision

Use one specialized simulator-compliance Judge invocation for both curated
calibration and production Qualification. It prepends a separate, structured
evidence block to the Transcript and trace input. The ordinary `GeneralJudge`
interface and every criterion description remain unchanged.

# Why

The evidence is part of the governing Scenario contract, not a Judge rule.
Keeping the seam specialized prevents false grounding failures and preserves
the hashes and validation of historical Qualification evidence.

# Revisit when

Revisit if the shared Judge gains a typed evidence channel that preserves
historical contracts, or if curated Scenarios gain declared Knowledge levels
and `goal_facts` in their schema.
