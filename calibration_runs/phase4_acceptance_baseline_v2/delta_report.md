# Phase 4 Acceptance Delta

## First acceptance run → baseline

The first live acceptance run exposed the Phase 4 calibration findings that
became M9, M10, and N6, along with defects in the D1/D4 acceptance setup and
missing persisted per-turn verdicts. The approved fixes introduced the strict
J1 confirmation gate, acknowledgment-before-matching in J5, separate D1
same-turn and submit-on-reask modes, the corrected D1 utterance and D4
checkpoint flow, and verdict persistence.

In `phase4_acceptance_baseline`, recall then passed completely with the required
D1 and D4 sources, zero errors, and zero degraded checks. Precision remained
red on two N=1 `judge:goal_completion` rulings:

- J1 confirmation re-asked after “Fine, yes. Schedule the $40 payment…” and
  “Yes. Schedule it now.” instead of submitting.
- J1 card-switch ignored a question about the freshly displayed $310.45
  statement balance and $210.45 remaining statement balance, then advanced to
  the date prompt.

## Baseline → v2

M11 widened only the gate-local finite allowlist to accept a leading direct
affirmation with trailing content, while decline detection takes precedence
and the M9 mid-message proceed-demand remains a re-ask. M12 promoted the mock's
displayed-amount question depth limit: it now answers from the already-fetched
options state and continues with the pending slot in the same response, without
an LLM or additional tool call.

`phase4_acceptance_baseline_v2` passes overall, recall, and precision at N=1:

- 21 completed runs; 0 errors; 0 degraded checks.
- D1 same-turn: `assertion:validated_submit`.
- D1 at the gate: `judge:explicit_confirmation`.
- D4 missing warning: `judge:warning_acknowledged`.
- All 21 `run.json` artifacts contain persisted per-turn verdict arrays.
- Harness LLM calls: 110; cluster-label LLM calls: 0.

The initial v2 execution encountered eight transient connectivity errors during
the network outage. Only those error rows were resumed after connectivity
returned; the final v2 artifacts contain no errors.
