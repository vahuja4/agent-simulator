---
title: Preserve every live Episode identity and report usage
category: reliability
symptoms:
  - One infrastructure exception cancels siblings without per-Episode attribution.
  - A completed live gate cannot report billed token usage by model role.
---

# Question

How should a fixed-denominator live gate retain honest attribution when
infrastructure fails and preserve provider usage evidence?

# Decision

During fan-out, each Episode catches and persists its own error or interruption;
one ordinary error never cancels sibling Episodes. Each successful live model
call also persists its provider usage block. Gate reports derive actual per-role
cost from the price table verified on the run date, and define cache-hit rate as
cached input tokens divided by all input tokens for that role.

# Why

Per-Episode persistence keeps infrastructure failures in the fixed denominator
with exact identity. Raw usage blocks preserve the billing evidence needed to
recompute cost if a reporting formula or price source is questioned.

# Revisit when

Revisit the cost calculation when OpenAI pricing changes; historical runs retain
their dated rates and raw usage blocks.
