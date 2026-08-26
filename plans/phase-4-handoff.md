# Phase 4 Handoff

## Start here

Read, in order:

1. `plans/agent-simulator-design-plan.md`
2. `plans/phase-3-baseline.md`
3. `plans/phase-4-build.md`
4. This note

Phase 3 is snapshotted by tag `phase-3-closed` at commit `9c74cd6`. The generic
plugin refactor remains deferred until after Phase 5.

## Current state

Phase 4 implementation is complete locally but not yet closed:

- Generic async capped/resumable batch runner with atomic artifacts.
- Explicit persona-only overlays that cannot mutate scenario semantics.
- Separate `pass`, `fail`, `task_incomplete`, and `error` outcomes.
- Per-run degraded checks and harness LLM-call counts; batch totals include
  optional cluster-label calls.
- Mechanical replay emission; D1–D7 replay tests reproduce tool-call sequences.
- Deterministic FailureRecord clustering; optional one-call cached labels.
- Static artifact-only Markdown report.
- Generic data-driven two-sided acceptance evaluator.
- Eight scripted recall rows: D1 same-turn, D1 at-the-gate, and D2–D7.
- Precision: all 13 defects-off scenarios x configurable `N`, with zero fail,
  error, or degraded checks required by the mock matrix.
- AST coupling test enforces that new Phase 4 modules use only generic seams.

Offline suite: **244 passed, 1 live test deselected**. The host Conda
`readline` extension segfaults pytest startup; use:

```sh
python -c 'import sys; sys.modules["readline"] = None; import pytest; raise SystemExit(pytest.main())'
```

## Live acceptance blocker

### N=1 diagnostic ledger

- **M9 confirmed real:** the faithful J1 gate submitted after “details right” plus a
  proceed-demand because shared substring confirmation parsing leaked into the final
  submission gate. The fix is the gate-local strict affirmation classifier; shared
  mid-flow assent parsing is unchanged.
- **M10 confirmed real:** after an out-of-scope J5 explanation, acknowledgment text was
  resolved through the lone-payment `it` substring shortcut and offered the unrelated
  $150 payment. Closing detection now precedes payment matching after an explanation,
  while explicit new cancellation requests still match.
- **N6:** the D4 diagnostic's early `scenario_success` failure is an N3-family ordered-
  criterion recurrence recorded as judge variance. No judge wording changes in this
  round; precision measures its rate.
- **M11 confirmed real:** M9's full-utterance J1 gate allowlist re-asked after the live
  leading affirmations “Fine, yes. Schedule the $40 payment…” and “Yes. Schedule it
  now.” The gate now accepts a finite affirmation at the start of the trimmed message
  while giving any later decline precedence; mid-message affirmation fragments remain
  conservative re-asks.
- **M12 promoted depth limit:** one N=1 precision judge penalized the mock for ignoring
  a question about the freshly displayed Freedom Unlimited amounts and proceeding to
  the date slot. The run stopped before payment completion. The mock now answers such
  questions deterministically from its fetched options state, then continues with the
  pending slot in the same reply, with no LLM or new tool call. This is recorded as
  N6-family ruling variance because a prior sample explicitly declined to penalize the
  same behavior.
- **M13 confirmed real, fixed:** explicit corrected amounts now override displayed
  option labels after a card switch; see `docs/reports/luna-gate-failure-evidence.md`.
  Resolution evidence: `calibration_runs/simulator_luna_n3_pressure_fix/seed-{0,1,2}/summary.json`.
- **M14 confirmed real, fixed:** the simulator prompt now grounds "today" in the
  fixture clock, preventing the real host date from conflicting with the mock's frozen
  date. Resolution evidence: the same passing N=3 summaries.
- **M15 confirmed real, fixed:** a pronoun retry for a non-cancellable payment now
  re-explains that payment instead of substituting the unrelated $150 payment; see
  `docs/reports/luna-gate-failure-evidence.md`. Resolution evidence: the same passing
  N=3 summaries.

The one-command live batch was attempted at:

`calibration_runs/phase4_acceptance/`

The two assertion-only rows completed correctly:

- D1 same-turn -> `assertion:validated_submit`
- D2 -> `assertion:refetch_after_card_switch`

The other 19 LLM-backed runs recorded `error` with
`APIConnectionError: Connection error` because sandbox network escalation was
rejected. This was correctly kept distinct from agent failures. No LLM call
reached the service, so the manifest total is currently zero.

The user must explicitly authorize sending the synthetic scenarios,
conversations, and traces—including tool arguments/results—to OpenAI's API.
Once authorized, resume only the errors with:

```sh
python scripts/run_calibration.py \
  --acceptance \
  --runs 1 \
  --concurrency 6 \
  --retry-errors \
  --out calibration_runs/phase4_acceptance
```

Do not add `--label-clusters` for the closure run; labels are optional and
would add calls without affecting membership or acceptance.

## Closure checks

Expected after the authorized retry:

- Recall passes all 8 rows with their exact named sources.
- Precision covers 13 scenarios once each, with only `pass` or
  `task_incomplete`, zero `error`, zero `fail`, and zero degraded checks.
- `acceptance.json` reports overall pass.
- `report.md`, `clusters.json`, and every failed run's `replay.json` exist.
- `manifest.json` reports per-run and total LLM calls.

If the live gate finds judge noise, follow amendment 24: any new/changed judge
wording must be calibration-style live-verified before closure. Do not change
mock behavior without separate approval.

Finally rerun the offline suite and `git diff --check`. Phase 4 source and docs
are currently uncommitted; inspect the working tree and commit only when the
user requests it.
