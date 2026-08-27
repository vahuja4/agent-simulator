---
title: J1 Goal replacement is distinguished by explicit abandonment
category: architecture
symptoms:
  - A multi-parameter payment change could be misclassified as goal shift.
  - A replacement payment could retain staged state from an abandoned Goal.
---

# Question

When is a changed J1 payment instruction a goal shift rather than a
mid-conversation correction, and what constitutes a J1 multi-intent turn?

# Decision

Each complete J1 payment instruction is a distinct Goal. Explicit abandonment
and complete replacement is goal shift; preserving the instruction while
amending one or more parameters is mid-conversation correction. One turn with
two independently actionable payment instructions is multi-intent turn.

# Why

Parameter count does not identify the state transition. Correction exercises
re-validation of preserved staged state; goal shift exercises discarding that
state and preventing abandoned-instruction submission or parameter bleed.

# What would make us revisit it

Revisit the represented scope when J2-J5 graphs make cross-Journey Goal shift
available. New definition ambiguities still require an explicit boundary
ruling before admission.
