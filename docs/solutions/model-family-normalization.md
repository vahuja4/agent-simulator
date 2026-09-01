---
title: Compare model families rather than model aliases
category: architecture
symptoms:
  - GPT minor aliases pass a family-separation check against another GPT minor.
  - Reports claim separation for `gpt-5.6-luna` and `gpt-5.5`.
---

# Question

What identity should model-family separation compare?

# Decision

After removing a dated snapshot suffix, GPT aliases normalize to their major
family. Therefore `gpt-5.6-luna` and `gpt-5.5` both normalize to `gpt-5` and
cannot form a reported simulator/Judge pair.

# Why

Minor versions, tiers, and aliases are model names inside the same GPT family.
Comparing full aliases made the enforcement flag pass while violating the
family-separation invariant.

# Revisit when

Revisit if the model provider publishes a stable, machine-readable family
identifier that is more authoritative than name normalization.
