# Phase 3 Baseline

Snapshot: lightweight tag `phase-3-closed` at commit `9c74cd6` (`Close Phase 3
baseline`). The tag captures the live-verified Phase 3 implementation and its
calibration artifacts before the Phase 4 planning changes.

## Offline baseline

Verified 2026-08-13 on Python 3.12.9: **216 passed, 1 live test deselected**.
The host Conda `readline` extension segfaults during pytest startup, so this run
preloaded `readline` as unavailable; collection and the complete offline suite
then ran normally.

## Live baseline

Defects off: **13/13 scenarios pass under the final committed wording with zero
judge noise**. The original full run has 12 final passes plus the pre-N4 pressure
failure; the final thirteenth pass is the M6/N5 faithful re-verification recorded
in the Step 3 report addendum.

| Defect | Expected source(s) | Phase 3 evidence |
|---|---|---|
| D1 | `assertion:validated_submit` for the same-turn shape; `judge:explicit_confirmation` for the at-the-gate shape | deterministic mock test; `step3_defects/D1_v2/` |
| D2 | `assertion:refetch_after_card_switch` (also `amount_in_options`); defense in depth from `judge:tool_output_truth` and `judge:card_switch_reset` | deterministic mock test; `step3_defects/D2/` |
| D3 | `judge:honest_failure` (also `readable_api_errors`) | `step3_defects/D3/` |
| D4 | `judge:warning_acknowledged` | `step3_defects/D4_v2/` |
| D5 | `judge:card_disambiguation` | `step3_defects/D5/` |
| D6 | `judge:journey_scoping` | `step3_defects/D6/` |
| D7 | `judge:external_account_caveat` | `step3_defects/D7/` |

Primary pointers: [`step3/REPORT.md`](../calibration_runs/step3/REPORT.md),
[`step3/summary.json`](../calibration_runs/step3/summary.json), and
[`step1/REPORT.md`](../calibration_runs/step1/REPORT.md). The `step3_defects/`
and `step3_verify_*/` directories contain the source-tagged per-run traces and
transcripts cited above.

## Characterization audit

No tests were added: all six requested seams already had direct, non-duplicative
coverage.

| Area | Existing pinning coverage |
|---|---|
| Tool-call sequences | `test_e2e.py`; J1–J5 mock journey tests |
| Trace serialization round-trip | `test_trace.py`; `test_e2e.py`; deserialized assertion test |
| Assertion outcomes | `test_assertions.py`; `test_assertions_defects.py` |
| Criterion activation, trigger on/off | `test_criteria.py` |
| Scenario validation | `test_scenario.py` schema errors and 13-file library lint |
| Script replay | `test_script.py::test_replay_script_from_recorded_trace_reproduces_tool_calls` |
