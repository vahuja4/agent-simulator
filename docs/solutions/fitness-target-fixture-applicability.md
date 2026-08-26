---
title: Fitness-target fixture applicability follows the mock branch inputs
category: architecture
symptoms:
  - A planted defect was treated as applicable to every cell in its journey.
  - The defect toggle had no observable effect for some fixture states.
---

# Question

When should a data-gated mock defect be attached to a Coverage cell?

# Decision

Declare every fixture fact needed to reach the toggled branch. D4 requires an
active AutoPay enrollment, a defined minimum due, and a representable fixed
amount below that minimum. D6 requires a scheduled AutoPay payment; an active
AutoPay enrollment alone is insufficient because J5 filters scheduled-payment
records rather than enrollment records.

# Why

A journey ID establishes the workflow but does not guarantee the data that
makes a defect observable. Without these predicates, fitness coverage can claim
D4 or D6 for a cell in which toggling the defect cannot change behavior.

# Revisit when

Revisit if J3 or J5 makes these fixture facts journey-level preconditions, or
if the mock derives pending AutoPay payments directly from active enrollments.
