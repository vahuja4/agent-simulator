---
title: Validate committed Qualification snapshots semantically
category: scenario-synthesis
symptoms:
  - Committing a valid evidence bundle invalidated its admission.
  - Reusing a terminal Candidate derived a new Qualification ID after the commit.
---

# Question

How should committed Qualification evidence remain trustworthy when the evidence commit
necessarily changes repository revision and dirty-state metadata?

# Decision

For a terminal Candidate, follow the Qualification ID recorded in `terminal.json`.
Validate the persisted snapshot's own hash and require its semantic inputs—configuration,
models, prompts, Fixture, and reviewed contracts—to match current inputs. Repository
revision and dirty state remain recorded evidence but may drift for completed admission
validation and reporting. In-progress resume continues to require the exact snapshot hash.

# Why

Repository state changes when durable evidence is committed, so requiring a historical
admission to equal the current repository-state hash creates a circular invalidation.
The semantic inputs determine Scenario behavior and admission; retaining strict equality
for them catches meaningful drift without invalidating evidence merely because it landed.

# What would make us revisit it

Revisit if evidence is produced from a detached immutable revision that can include its
own commit identity without a circular write, or if repository metadata becomes a
semantic execution input.
