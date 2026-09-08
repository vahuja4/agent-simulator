---
title: Express "cell lock already held" as a separate function, not a flag
category: architecture
symptoms:
  - A `_cell_lock_held` boolean threaded through lifecycle helpers decided whether to acquire the cell lock.
  - The critical-section boundary moved with the caller, so the same helper ran its validation inside or outside the lock depending on who called it.
---

# Question

When a lifecycle step (finalizing an admission, producing a replacement
Candidate) can be reached both from a command that already holds the Coverage
cell lock and from one that does not, how should the helper learn which case it
is in?

# Decision

Two named entry points over one locked core. `_resume_incomplete` validates the
admission evidence, acquires the cell lock, and calls `_commit_admission`;
`_resume_incomplete_locked` does the same without acquiring, and its docstring
states the precondition. `_commit_admission` itself documents that it must be
called with the lock held. No boolean parameter selects the behavior.

`exclusive_lock` stays a plain `O_EXCL` lockfile: not re-entrant, no
owner/depth tracking. Crash recovery depends on that lock being dumb.

# Why

A flag makes lock ownership a caller-supplied claim that the helper cannot
check, and it silently relocates the critical section. Two functions make the
two call shapes visible at the call site and greppable, and keep the locked
core's precondition in one place. The alternative — a re-entrant lock — would
need ownership metadata that survives crashes, which is exactly the complexity
the lockfile design avoids.

# Revisit when

`produce_candidate` in `candidate.py` still takes `_cell_lock_held`; apply the
same split there when that file is next simplified. Revisit the whole pattern
only if a third lifecycle command needs to compose these steps under one lock,
at which point an explicit lock-token object may be cheaper than more pairs.
