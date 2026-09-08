---
title: Calibration artifacts serialize through to_dict and atomic writes
category: architecture
symptoms:
  - Per-scenario calibration JSON hand-built verdict dicts that duplicated `TurnVerdict.to_dict`.
  - Gate summary and Episode records were written with plain `write_text`, so a crash mid-write left a truncated file the resumable gate would read back.
---

# Question

When `scripts/run_calibration.py` writes run artifacts, may it reuse the
library's `to_dict` methods even though that changes JSON key order, and may
gate writes go through the atomic evidence helpers?

# Decision

Yes to both. Verdicts, failures, and traces in calibration JSON are produced by
their `to_dict` methods. Gate Episode records, `summary.json`,
`persona-fidelity-spot-check.json`, and `REPORT.md` are written with
`scenario_synthesis.evidence.atomic_json` / `atomic_text`. Key order inside a
calibration JSON object is not a contract; only parsed content is. The
per-scenario calibration `.json` and `summary.json` in the plain calibration
mode keep `indent=2` without `sort_keys`, so they stay outside the atomic helper.

# Why

Hand-rolled dicts drift silently when a field is added to a verdict type, and
every reader of these files parses them with `json.loads`. Atomic writes cost
nothing in output bytes and remove a truncated-artifact failure mode in a gate
that is explicitly resumable.

# Revisit if

A consumer starts diffing calibration artifacts byte-for-byte, or a gate
artifact needs a schema the library types do not carry.
