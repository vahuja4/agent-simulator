# Scenario Synthesis Phase 4 Notes

**Date:** 2026-08-17
**Scope:** Phase 4 only; no live dry-runs, candidate filtering, seed weighting,
feedback loop, shared judge wording changes, mock changes, or Phase 5 work.

## Decisions

- Every candidate is passed through the existing `run_scenario` twice. The
  faithful configuration sets every `MockConfig` defect toggle to `False`; the
  targeted configuration enables only toggles mapped from that blueprint's
  policies.
- J1 policy targeting is explicit and reviewable: `explicit_confirmation` maps
  to both independently reproducible D1 toggles, `card_switch_resets` to D2,
  `tool_output_truth` to D3, and `disambiguate_last_four` to D5.
- Run classification is one of `simulator_invalid`, `agent_fail`, `agent_pass`,
  or `error`. A faithful run is marked `solvable` only when classified
  `agent_pass`; therefore a faithful `agent_fail` makes the scenario candidate
  suspect rather than being interpreted as a mock-agent defect.
- `defect_sensitive` is measurement-only and is true only when a targeted
  toggle exists and the targeted run records a structured assertion or judge
  failure. Neither classification nor sensitivity removes a candidate.
- Simulator compliance is evaluated after the orchestrated run with a separate
  three-criterion judge covering factual grounding, confirmation timing, and
  goal persistence. The shared `DEFAULT_CRITERIA` and specialist wording were
  not changed.
- Each run records procedure edges hit, assertion failures fired, judge
  criteria activated in verdicts, and trace-derived tool-result classes. The
  manifest appends candidate records containing both configurations and keeps
  simulator-invalid counts separate from agent failures in its summary.
- Live execution exists only at the explicit entry point
  `.venv/bin/python -m scripts.dryrun_scenarios`. It consumes realized manifest
  entries and was not invoked in this phase.

## Done-when evidence

- A seeded, two-candidate stubbed batch wrote both faithful and targeted records
  per candidate without filtering either an `agent_fail` or a
  `simulator_invalid` result.
- The stubbed batch separately reported one faithful `agent_pass` and one
  faithful `agent_fail`; its targeted records demonstrated assertion-based
  defect sensitivity and simulator-invalid classification.
- Offline coverage assertions verified all four required dimensions in the
  appended manifest record.
- Targeted Phase 4 tests: **3 passed**.
- Full offline suite: **282 passed, 1 deselected** via
  `.venv/bin/python -m pytest` on Python 3.12.12.
- Live LLM calls and live dry-runs: **none**.
- Phase 5: **not started**.
