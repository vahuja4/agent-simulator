---
title: Finalize Qualification against its persisted snapshot
category: scenario-synthesis
symptoms:
  - Writing live Qualification evidence changed repository dirty state and invalidated the same bundle.
  - A retry derived a new Qualification ID instead of resuming complete pre-Admission evidence.
---

# Question

Which snapshot governs finalization when writing a Qualification changes repository
metadata, and how should the public command find complete evidence after that drift?

# Decision

Validate a complete Qualification against the snapshot stored in its own bundle, while
requiring its semantic configuration to match current inputs. If no Candidate terminal
exists, discover the newest complete bundle for the same Candidate, runner, and provider
and resume it before creating a new Qualification.

# Why

Repository dirty state is changed by writing the evidence itself and is not a semantic
execution input. Recomputing it during finalization creates a circular harness failure;
deriving a new run ID on retry would then spend money and replace valid stochastic evidence.

# What would make us revisit it

Revisit if Qualification evidence is written outside the repository, if repository state
becomes a semantic execution input, or if multiple resumable bundles require an explicit
operator selection policy rather than newest-valid-first discovery.
