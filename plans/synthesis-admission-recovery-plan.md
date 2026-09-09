# Synthesis admission recovery plan

Written 2026-09-09 against `main` at `9942257`. Goal: raise the probability that a
produced Candidate is admitted, by making Qualification verdicts more correct.
No step here lowers the bar; each one removes a way the harness blames the
simulated customer for a failure that belongs elsewhere.

## Evidence this plan rests on

State of `synthesized_scenarios/` on 2026-09-09:

| Fact | Value |
|---|---|
| Eligible Coverage cells (planner) | 4,368 |
| Cells ever attempted | 11 |
| Candidates produced | 13 |
| Qualification bundles | 11 |
| Admitted | 2, both for cell `ecbf1aff…` |
| Currently counted as covered | 0 |

Why the two admissions do not count:

- Ordinal 0 (2026-08-29) was invalidated as a harness fault: Judge rulings came
  back empty.
- Ordinal 1 (2026-08-31) is marked `config-hash-mismatch`. Since it was
  admitted, the compliance criterion set was added to the config (2026-09-01),
  and the realization prompt and simulator model changed (2026-09-03). Nobody
  re-qualified it.

Why the nine rejections happened, from each bundle's recorded attribution:

| Attribution | Count |
|---|---|
| simulator-compliance | 7 |
| defects-off-precision | 1 |
| judge check on the defect-on side, not clean detection | 1 |

The seven compliance rejections, read against their transcripts:

| Bundle | Cell | What the judge said | Assessment |
|---|---|---|---|
| `5787127b` | `6af931a6` ord 0 | Customer never switched to the second card | Fair. Simulator failure. |
| `9ce0907b` | `0743dfb4` ord 0 | High-knowledge customer did not state the confirmation rule unprompted | Fair reading; the bar is unnatural. |
| `a4b34a42` | `ad4c2dc7` ord 0 | Same as above | Same. Also a garbled stop marker leaked into the customer's last message and the mock read it as a refusal. |
| `e8c7fb23` | `ecbf1aff` ord 0 | Low-knowledge customer "invented" that statement balance means the whole bill | Too strict. Human review already overturned it as a criterion-scope defect (ledger). |
| `91e9d6f1` | `89c8eb9d` ord 0 | Declared correction "not evidenced so far" | Misattributed. Episode ended at turn 2 because the clean mock ignored the card correction. Also the blueprint declared an amount correction while the realized goal told the customer to correct the card. |
| `e23b97e7` | `97efe211` ord 0 | Knowledge reliance "not yet" shown; channel noise cosmetic | Misattributed. Simulator sent its stop marker after its first message. The noise finding is fair: two trailing characters is cosmetic, a realization failure. |
| `f703deec` | `6af931a6` ord 1 | Fluency gap "has not appeared yet" | Misattributed. Main judge halted the episode at turn 2 over the agent's option-fetch order. |

Structural cause behind the three misattributions: in
`scenario_synthesis/qualification.py`, the compliance judge runs once after the
episode on whatever transcript exists, and a compliance failure overrides every
other classification. On a transcript truncated by a simulator stop, a judge
halt, or a mock fault, "not yet" becomes "fail" and the rejection is charged to
the simulator and consumes the cell's regeneration budget. The design plan
records the same premature-ruling family for the main judge as N6.

## Ordering constraint

Any change to a prompt, criterion set, or config changes the snapshot hash and
retires every existing admission. All semantic changes therefore land before
the single live re-qualification batch, not interleaved with it.

## Phase 1: offline fixes, no LLM calls, one worktree each

1. **Stop charging the customer for truncated episodes.**
   Where: `scenario_synthesis/qualification.py`, the episode classifier after
   `judge_simulator_compliance`.
   Change: if the episode ended by simulator stop, judge halt, or max turns
   before the customer's evidence could appear, record compliance as
   `not-evaluable` and attribute the rejection to what ended the episode.
   Proof: replay the nine rejected bundles' recorded transcripts through the
   new classifier. Expected: `91e9d6f1`, `e23b97e7`, `f703deec` flip to their
   true cause; the other six are unchanged. Commit that replay as a regression
   fixture.

2. **Fix stop-marker handling.**
   Where: `agentsim/simulator.py`, the `STOP_SENTINEL` substring check.
   Change: match a tolerant pattern, strip it from the message, and treat a
   stop on the customer's first turn with no verdict as a simulator fault, not
   a compliance fault.
   Proof: the two recorded episodes (`a4b34a42` defects-off rep 0, `e23b97e7`
   defects-off rep 0) plus unit cases for garbled markers.

3. **Triage the card-correction failure against the mock.**
   Where: `agentsim/adapters/mock_paycard/`, scripted replay.
   The clean mock answered "I meant the card ending in 0767, not 9013" with
   "How much would you like to pay?" and no refetch, in two of three
   defects-off repetitions of `91e9d6f1`. The mock is deterministic, so a
   two-turn scripted replay settles it. If mock bug: M-series ledger entry and
   a fix under the mock-change approval rule in AGENTS.md. If judge noise:
   N-series entry.
   Do this first. It is a five-minute check and decides whether the mock needs
   an approved fix before any live run.

4. **Validate the declared Complication at realization time.**
   Where: `scenario_synthesis/realization_provider.py`, `validate_surface`.
   Today it checks fact tokens, knowledge surface, and invented numbers, not
   complication semantics. Add a per-complication surface check so a blueprint
   that declares an amount correction cannot realize as a card correction, and
   channel noise must be instructed as material rather than cosmetic.
   Proof: the `91e9d6f1` and `e23b97e7` blueprints against their realized
   scenarios fail the new check; every currently admitted or rejected bundle
   whose realization matched its blueprint still passes.

## Phase 2: definition changes, each needs explicit approval

5. **Make high Knowledge realizable.**
   Two rejections came from the rule that a high-knowledge customer states a
   rule unprompted. Cheapest fix inside the current definition: realization
   puts the rule statement into the goal text the customer opens with, so it is
   mechanically present. Measure in Phase 3. If rejections persist, the real fix
   is redefining high Knowledge as correctly acting on the rule, which is a
   CONTEXT.md and persona-archetypes contract change with a live
   persona-fidelity spot-check.

6. **Narrow the factual-grounding criterion.**
   CONTEXT.md's sealed-world rule already allows an incorrect label for a real
   fact at low Knowledge. The criterion wording does not cite it, and the ledger
   records one rejection overturned on exactly this point. Reword the criterion
   to cite the rule. Judge criterion wording changes require explicit approval
   and live verification before the phase closes (AGENTS.md). This is the last
   semantic change before re-qualification.

## Phase 3: bookkeeping and one live batch, on explicit request

7. **Invalidate the three misattributed rejections as harness faults.**
   The Rejection ledger supports candidate rejection invalidation and it returns
   the cell's regeneration budget. The CLI exposes only `invalidate-admission`,
   so this step adds the rejection form to `scenario_synthesis/cli.py`.

8. **Re-run the same eleven cells live, N=3.**
   Same cells as before so the comparison is clean. Success criterion: at least
   8 of 11 admitted, and zero rejections attributed to compliance on a truncated
   transcript. Baseline for comparison: 2 admissions from 13 candidates, both
   for one cell, neither currently counted. Model-family separation applies as
   recorded in AGENTS.md.

9. **Scale production only after step 8 passes.**
   The per-cell manual produce/qualify loop then becomes the bottleneck. That
   is separate work and out of scope here.

## What would change this plan

- Step 3 finds a mock bug: fix the mock before Phase 3, and expect every
  defects-off run involving a mid-flow card correction to have been affected.
- Step 8 admits fewer than 8 of 11: read the new rejections the same way as the
  table above before touching any criterion. Do not loosen a criterion to reach
  the number.
