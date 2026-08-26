---
title: Slice 2 plans authored paths and blocks unknown journey expansions
category: architecture
symptoms:
  - An unauthored journey graph could disappear from coverage planning.
  - Generator reachability could be mistaken for eligibility.
---

# Question

How should Slice 2 count cells and report J2–J5 while only the J1 graph exists?

# Decision

Enumerate the authoritative cell denominator from authored, reviewed paths: J1
currently has 4,092 eligible cells. Emit explicit BLOCKED journey-path axis
obligations for J2–J5, and do not invent their path, edge, pair, or cell IDs.
Contract-applicability holes remain BLOCKED until a reviewed ADR 0004 exclusion
exists; the report lists mechanically derived exclusions as proposals only.

# Why

An invented path would create false precision, while omission would hide owed
coverage. This preserves default eligibility, separates BLOCKED from UNCOVERED,
and makes the current denominator reproducible from reviewed inputs.

# What would make us revisit it

Revisit when a J2, J3, J4, or J5 graph and its fixture-state classes are
reviewed, or when proposed pair exclusions are approved and entered into the
reviewed exclusion contract.
