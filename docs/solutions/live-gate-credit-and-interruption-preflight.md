---
title: Fail closed before live gates and preserve every Episode identity
category: reliability
symptoms:
  - A live gate starts without enough API credit to finish its denominator.
  - One infrastructure exception cancels siblings without per-Episode attribution.
---

# Question

How should a fixed-denominator live gate prove sufficient credit before starting
and retain honest attribution if infrastructure still fails?

# Decision

Every live entry point requires an operator-supplied USD credit lower bound and
a conservative per-call USD ceiling. The derived command ceiling is printed and
the command refuses unless the lower bound strictly exceeds it. During fan-out,
each Episode catches and persists its own error or interruption; one ordinary
error never cancels sibling Episodes.

# Why

The installed OpenAI client has no supported available-balance resource. An
explicit lower bound is auditable and fail-closed, while per-Episode persistence
keeps infrastructure failures in the fixed denominator with exact identity.

# Revisit when

Revisit if a supported balance API becomes available, or if pricing-aware token
accounting can replace the conservative per-call ceiling without weakening the
pre-flight assertion.
