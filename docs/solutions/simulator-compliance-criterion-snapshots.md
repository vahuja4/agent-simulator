---
title: Qualification evidence validates against its snapshotted compliance criteria
category: architecture
symptoms:
  - Adding a simulator-compliance criterion can invalidate immutable historical Qualifications.
  - Current code can expect rulings that did not exist when an Episode was judged.
---

# Question

Which simulator-compliance criterion set governs validation of persisted
Qualification evidence after the current set changes?

# Decision

Each new config snapshot records its simulator-compliance criterion IDs, and
Qualification evidence validates against that recorded set. Snapshots created
before the field existed use the historical four-criterion set. They are not
upgraded or reinterpreted under the current five-criterion set.

# Why

Qualification evidence is immutable and must remain attributable to the
configuration that produced it. Validating old rulings against current code
would retroactively make complete historical evidence appear incomplete.

# What would make us revisit it

Revisit when criterion definitions receive their own versioned artifact or
content hashes, or when the Qualification evidence schema is deliberately
versioned to carry more than criterion identity.
