---
title: Resume complete Qualification evidence before admission
category: scenario-synthesis
symptoms:
  - Complete live Episodes were rejected as duplicate or foreign with a relative output root.
  - Retrying after interruption before admission would rerun Qualification Episodes.
---

# Question

How should Qualification handle resolved evidence references when its artifact root is
relative, and how should it resume after all Episodes are written but before admission?

# Decision

Normalize the Qualification root and bundle before comparing contained evidence paths.
When a bundle has complete, valid `qualification.json` and Episode evidence but no
`admission.json`, evaluate admission from that retained evidence under the matching
configuration snapshot and finish the terminal transition without invoking the runner.

# Why

Evidence references intentionally resolve paths before validating containment. Comparing
those paths to an unresolved bundle falsely classified in-bundle Episodes as foreign.
Once the complete immutable evidence exists, rerunning live Episodes would violate
idempotent resume and change both cost and stochastic evidence.

# What would make us revisit it

Revisit if Qualification adopts an external-retention form or a new lifecycle state that
cannot prove the Episode set complete before admission evaluation.
