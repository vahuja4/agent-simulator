---
title: Fail closed before live gates and preserve every Episode identity
category: reliability
symptoms:
  - A live gate starts without enough API credit to finish its denominator.
  - One infrastructure exception cancels siblings without per-Episode attribution.
  - A completed live gate cannot report billed token usage by model role.
---

# Question

How should a fixed-denominator live gate prove sufficient credit before starting
and retain honest attribution if infrastructure still fails?

# Decision

Every live entry point requires an operator-supplied USD credit lower bound and
a conservative per-call USD ceiling. The derived command ceiling is printed and
the command refuses unless the lower bound strictly exceeds it. During fan-out,
each Episode catches and persists its own error or interruption; one ordinary
error never cancels sibling Episodes. Each successful live model call also
persists its provider usage block. Gate reports derive actual per-role cost
from the price table verified on the run date, and define cache-hit rate as
cached input tokens divided by all input tokens for that role.

# Why

The installed OpenAI client has no supported available-balance resource. An
explicit lower bound is auditable and fail-closed, while per-Episode persistence
keeps infrastructure failures in the fixed denominator with exact identity.
Raw usage blocks preserve the billing evidence needed to recompute cost if a
reporting formula or price source is questioned.

# Revisit when

Revisit if a supported balance API becomes available, or if pricing-aware token
accounting can replace the conservative per-call ceiling without weakening the
pre-flight assertion. Revisit the cost calculation when OpenAI pricing changes;
historical runs retain their dated rates and raw usage blocks.
