# Synthesis admission recovery plan

Written 2026-09-09 against `main` at `9942257`. Revised the same day against
`88f47b5` after every claim was checked against the recorded Qualification
evidence and the two mock exchanges were replayed deterministically. Goal
unchanged: raise the probability that a produced Candidate is admitted by
making Qualification verdicts more correct. No step lowers the bar; each one
removes a way the harness charges a failure to the wrong party.

## Evidence this plan rests on

State of `synthesized_scenarios/` on 2026-09-09:

| Fact | Value |
|---|---|
| Eligible Coverage cells (planner) | 4,368 |
| Cells with at least one Candidate | 8 |
| Candidates produced | 13 |
| Qualification bundles with an admission decision | 11 |
| Candidates produced but never qualified | 2 (`01bb058…` ord 1, `54c4af4…` ord 0) |
| Admitted | 2, both for cell `ecbf1aff…` |
| Currently counted as covered | 0 |
| Cells with regeneration budget exhausted | 1 (`6af931a…`, ordinals 0-2 all rejected) |

The first draft said eleven cells were attempted. Eight were. Three of the
eleven bundles are repeat ordinals of `ecbf1aff…` and `6af931a…`.

Why the two admissions do not count:

- Ordinal 0 (2026-08-29) was invalidated as a harness fault: Judge rulings came
  back empty (M-005).
- Ordinal 1 (2026-08-31) is marked `config-hash-mismatch`. Since it was
  admitted, the compliance criterion set was added to the config (2026-09-01)
  and the realization prompt and simulator model changed (2026-09-03). Nobody
  re-qualified it.

Why the nine rejections happened, by recorded attribution:

| Attribution | Count |
|---|---|
| simulator-compliance | 7 (one already superseded by `harness-fault` under N-007-S1) |
| defects-off-precision | 1 |
| unrelated-failure on the defect-on side | 1 |

The recorded attribution names only the first failing Episode. Reading every
failing ruling in every Episode gives a different picture:

| Bundle | Cell / ord | Every failing ruling | Root cause |
|---|---|---|---|
| `5787127b` | `6af931a` ord 0 | Rep 0: customer completed on the first card and never switched. Reps 1-2: mock re-asked for an amount instead of answering "which option is the whole bill", then staged an option the customer never chose. | Rep 0 simulator (fair). Reps 1-2 mock, M-019. |
| `f703deec` | `6af931a` ord 1 | Rep 0: main judge halted at turn 2 on the mock's option-fetch order; compliance then ruled the fluency gap "has not appeared yet". Reps 1-2: M-019. | Rep 0 truncation, N-010. Reps 1-2 mock. |
| `f8e71a6d` | `6af931a` ord 2 | Reps 0-1: M-019. Rep 2 passed. | Mock. |
| `91e9d6f1` | `89c8eb9` ord 0 | All six Episodes: the Blueprint declared an amount-type correction, the realized Goal told the customer to correct the card. Reps 0 and 2 additionally: the mock dropped "0767, not 9013" because the mention set included the current card. | Realization mismatch. Mock, M-018. |
| `e23b97e7` | `97efe21` ord 0 | All six Episodes: declared channel noise, realized as two trailing characters the judge called cosmetic. Rep 0 additionally: simulator sent its stop marker after its first message. | Realization mismatch. Simulator stop, N-010. |
| `9ce0907b` | `0743dfb` ord 0 | Three of six: high-Knowledge customer did not state the confirmation rule unprompted. Defects-off rep 2 failed on the mock's handling of the two-payment Goal, not yet triaged. | Knowledge definition. Possible mock gap. |
| `a4b34a42` | `ad4c2dc` ord 0 | All six: rule not stated unprompted. Rep 0 additionally: `】【STOP###` leaked into "Yes, please schedule it", and the gate's decline regex matched "stop". | Knowledge definition. Stop-marker leak. |
| `e8c7fb23` | `ecbf1aff` ord 0 | Rep 1: factual grounding treated a low-Knowledge belief as an invented fact. | Superseded. Criterion reworded and live-verified, rejection invalidated 2026-08-31 (N-007-S1). |
| `f6d4c015` | `01bb058` ord 0 | Defects-off 3/3 pass. Defect-on: `honest_failure` fired as expected, and so did `goal_completion`, `scenario_success`, `readable_api_errors`. Rejected because the defect-on side must carry exactly one failure. | Single-failure rule. |

Four structural causes:

1. In `scenario_synthesis/qualification.py` the compliance judge runs once on
   whatever transcript exists, a compliance failure overrides every other
   Episode kind, and `_decide_admission` checks compliance before kind. On a
   truncated transcript "not yet" becomes "fail" and is charged to the
   simulator. The termination cause is recorded only as free text in
   `termination.reason`; only the simulator-stop and max-turns strings are
   stable, a judge halt is the judge's prose.
2. Two deterministic mock defects, M-018 and M-019 in
   `docs/ledgers/mock-findings.md`. M-019 ended six of the nine defects-off
   Episodes for `6af931a…` and is the reason that cell's budget is exhausted.
   It bounds every low-Knowledge payment-amount-type cell, which is the
   canonical low-Knowledge realization in `realization_provider.py`.
3. `validate_surface` checks fact tokens, Knowledge surface, and invented
   numbers, not Complication semantics. Two of eight cells were realized with
   the wrong Complication and could never have passed.
4. The defect-on side requires exactly one failure. A dishonest-failure defect
   necessarily also fails goal completion, so a correctly detected planted
   defect is rejected as unrelated.

## Ordering constraint

Any change to a prompt, criterion set, config, or fixture changes the snapshot
hash and retires every existing admission. All semantic changes land before the
single live re-qualification batch, not interleaved with it.

## Phase 1: offline fixes, no LLM calls, one worktree each

1. **Gate slot extraction on turn intent in the mock. Needs explicit approval
   under the AGENTS.md mock-change rule.**
   Where: `agentsim/adapters/mock_paycard/agent.py` `handle_card_mention`,
   `j1_one_time.py` amount capture, and `parsing.py`.
   M-018 and M-019 share one cause: the mock mines every message for amounts,
   labels, and card numbers before deciding what the customer is doing. A
   question was mined for an amount and one was found; a negated mention was
   mined for cards and two were found. The fix is structural, not two patches:
   - Split the message into sentences. Slot extraction runs only on sentences
     that are not questions (ending in `?` or opening with an interrogative).
     Question sentences go to the answering path, which is extended to list
     the options with their fixture-state meanings when no label is named.
   - A card mention inside a negation window ("not", "instead of", "rather
     than") is excluded. One remaining non-negated card is the switch target.
   - A message with noise markers (no terminal punctuation and several
     candidate details, or tokens that match nothing) is not acted on. The mock
     reflects back its reading and waits for confirmation. This is the
     recovery behavior CONTEXT.md requires for channel noise, so the clean
     reference exhibits it rather than guessing.
   The principle: rules cannot make the mock understand more, but they can
   reliably make it act less. A miss becomes a clarifying question, never a
   staged payment the customer did not choose. An LLM classifier is excluded:
   it is an invariant, it breaks replayability and the defect on/off
   comparison, and it would need its own calibration.
   Proof: the three replays in the M-018 and M-019 ledger entries pass; the M3
   "this Freedom card" behavior and every planted D-series shape are unchanged
   under the defect-toggle suite; and a new corpus test runs every recorded
   customer turn from `synthesized_scenarios/runs/*/episodes/*-transcript.jsonl`
   through the gate and asserts no question turn captures an amount and no
   negated card is selected. Labeling that corpus once with an LLM, offline, is
   permitted so the test does not merely agree with its own regexes.
   Do this first. It decides whether `6af931a…` and `89c8eb9…` can be admitted
   at all, and it is independent of every judge or prompt change.

2. **Validate the declared Complication at realization time.**
   Where: `scenario_synthesis/realization_provider.py`, `validate_surface`.
   Change: a per-Complication surface check. A mid-conversation correction
   must realize the parameter the Blueprint names; channel noise must be
   instructed as material and requiring recovery, not cosmetic.
   Proof: the `91e9d6f1` and `e23b97e7` Blueprints against their realized
   Scenarios fail the new check; every other bundle's realization still passes.

3. **Stop charging the customer for truncated Episodes.**
   Where: `agentsim/orchestrator.py` and the episode classifier in
   `scenario_synthesis/qualification.py`.
   Change: the orchestrator records a structured termination kind
   (`judge-halt`, `simulator-stop`, `max-turns`, `judge-verdict`, `error`)
   alongside the free-text reason. If the Episode ended by judge halt,
   simulator stop, or max turns before the customer's evidence could appear,
   compliance is recorded as `not-evaluable` and the rejection is attributed
   to what ended the Episode.
   Proof: replay the nine rejected bundles' recorded artifacts through the new
   classifier. Expected: exactly one Episode changes, `f703deec` ord 1 rep 0,
   from simulator-compliance to an agent-side defects-off failure. `91e9d6f1`
   and `e23b97e7` do not change, because their other repetitions fail
   Complication evidence on complete transcripts. Commit the replay as a
   regression fixture.

4. **Fix stop-marker handling.**
   Where: `agentsim/simulator.py`, the `STOP_SENTINEL` substring check.
   Change: match a tolerant pattern, strip it before the text reaches the
   adapter, and treat a stop on the customer's first turn with no verdict as a
   simulator fault.
   Proof: the recorded `a4b34a42` defects-off rep 0 and `e23b97e7` defects-off
   rep 0 turns, plus unit cases for garbled markers. The `a4b34a42` case must
   reach the mock as "Yes, please schedule it" and be confirmed, not declined.

## Phase 2: definition changes, each needs explicit approval

5. **Make high Knowledge realizable.**
   Six of six `a4b34a42` and three of six `9ce0907b` Episodes failed the rule
   that a high-Knowledge customer states a rule unprompted. Cheapest fix inside
   the current definition: realization puts the rule statement into the Goal
   text the customer opens with, so it is mechanically present. Measure in
   Phase 3. If rejections persist, the real fix is redefining high Knowledge as
   correctly acting on the rule, which is a CONTEXT.md and persona-archetypes
   contract change with a live persona-fidelity spot-check.

6. **Decide the defect-on single-failure rule.**
   `f6d4c015` was the closest bundle to admission and was rejected only by this
   rule. Options: keep the rule and accept that dishonest-failure targets can
   never be admitted, or let each Fitness target declare the consequential
   criteria its defect necessarily also fails and require no failure outside
   that set. The second is a Fitness-target contract change. Recommendation:
   the second; a defect that fires exactly as planted is clean detection.

7. **A ledgered mock defect makes the cell BLOCKED; it does not reject the
   Candidate.**
   CONTEXT.md already defines BLOCKED as an eligible obligation the current
   implementation cannot realize for a recorded reason, engineering debt that
   trends to zero. A defects-off failure whose cause is a ledgered M-series
   entry is exactly that. Rule: such a failure moves the cell to BLOCKED with
   the M-number as the recorded reason, consumes no ordinal, and is attributed
   to the mock, never to the simulator. When the entry is resolved the cell
   returns to UNCOVERED. This replaces the first draft's question of whether a
   mock bug is a harness fault. It is a CONTEXT.md and planner change and
   needs explicit approval.

The factual-grounding criterion narrowing from the first draft is dropped. It
was done under N-007-S1 on 2026-08-31, live-verified, and the affected
rejection is already invalidated.

## Phase 3: bookkeeping and one live batch, on explicit request

8. **Re-attribute the mock-caused rejections and restore `6af931a…`.**
   `f703deec` ord 1 and `f8e71a6d` ord 2 failed on M-019 and, under decision
   7, should never have consumed ordinals. The historical records stay; add
   `invalidate-rejection` to `scenario_synthesis/cli.py` over the existing
   `qualification-invalidation` ledger stage so the two ordinals return, and
   record BLOCKED(M-019) as the cell's state until step 1 lands. `5787127b`
   stands on its rep 0 simulator failure. `91e9d6f1` stands as a realization
   defect. Before appending, reconcile the orphan run directory `de630451…`
   (episodes and a snapshot, no qualification record, no ledger entry) and the
   duplicate stub-run bundle for `f703deec`.

9. **Re-qualify all eight attempted cells live, N=3.**
   Per-cell expectation, so the batch is read against a prediction rather
   than a number:

   | Cell | Blocker before this plan | Expected after Phases 1-2 |
   |---|---|---|
   | `ecbf1aff` | admission retired by config drift only | admit |
   | `01bb058` | single-failure rule | admit if decision 6 changes the rule, else reject again |
   | `6af931a` | M-019, budget exhausted | admit if step 1 lands and step 8 restores budget |
   | `89c8eb9` | realization mismatch, M-018 | fresh ordinal 1 after step 2; admit if step 1 lands |
   | `97efe21` | realization mismatch, stop marker | fresh ordinal 1 after steps 2 and 4; uncertain, first material-noise realization |
   | `0743dfb` | high-Knowledge rule, untriaged two-payment mock behavior | uncertain until step 5 is measured |
   | `ad4c2dc` | high-Knowledge rule, stop marker | uncertain until step 5 is measured |
   | `54c4af4` | never qualified | unknown |

   Success criterion: at least six of eight admitted, zero rejections
   attributed to compliance on a truncated transcript, zero defects-off
   failures matching M-018 or M-019. Baseline: two admissions from thirteen
   Candidates, both for one cell, neither counted. Model-family separation
   applies as recorded in AGENTS.md.

10. **Scale production only after step 9 passes.**
    The per-cell manual produce/qualify loop then becomes the bottleneck. That
    is separate work and out of scope here.

## What this plan does and does not do

It does: stop three harness-side mechanisms from rejecting sound Candidates
(truncation charged to the simulator, a garbled stop marker read as a decline,
a mock that cannot handle two corrections J1 customers actually make); stop
realization from producing Candidates whose Complication can never be
evidenced; and make two admission rules explicit decisions instead of
accidents.

It does not: lower any criterion; fix the main judge's premature ordered-
criterion halts (N6 in the design plan), which will keep truncating Episodes
and now be attributed correctly rather than prevented; touch the untriaged
two-payment mock behavior in `9ce0907b`; or scale production. Steps 1, 5, 6,
and 7 each need an explicit approval before they can land. It does not make
the mock understand customers; it makes the mock ask instead of guess, and a
persona noisy enough to exhaust the turn budget with clarifications is the
measurable point at which an LLM classifier would be reconsidered.

## What would change this plan

- Step 1 is not approved: `6af931a…` and `89c8eb9…` stay blocked on the mock,
  the step 9 target drops to four of eight, and both cells should be marked
  BLOCKED with M-018 and M-019 as the recorded reason.
- Step 9 admits fewer than six of eight: read the new rejections the same way
  as the table above, every failing ruling in every Episode, before touching
  any criterion. Do not loosen a criterion to reach the number.
