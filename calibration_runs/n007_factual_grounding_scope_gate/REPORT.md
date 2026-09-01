# N-007 factual-grounding scope calibration gate

Date: 2026-08-31  
Simulator: `gpt-5.6-luna`  
Judge: `gpt-5.5`  
Configuration: defects off; the separation flag was enabled, but the then-current
name comparator incorrectly treated `gpt-5.6-luna` and `gpt-5.5` as different
families. Both are GPT-5-family models, so model-family separation was not achieved.

## Approved wording

> The customer simulator did not invent facts. Every card, account, amount,
> balance, date, prior action, or other fact about the customer's accounts,
> payments, or history that the customer claims must be available from the
> scenario goal, the supplied knowledge, or the conversation and tool history.
> The customer's beliefs about what terms mean, how domain concepts work, or
> what the assistant is able to do are outside this criterion: assess them
> under the knowledge-level rules, or under the false-premise rules when the
> belief concerns the customer's real account state.

## Result

The gate passed.

- Curated set: **39/39 selected Episodes passed** the ordinary Agent verdict
  and all three simulator-compliance criteria (13 Scenarios at N=3).
- Pilot cell: **1/1 passed** all four simulator-compliance criteria, including
  `simulator_factual_grounding` and `simulator_knowledge_level_evidence`.
- Mock defect toggles remained off. No curated Scenario, mock behavior, or
  other Judge criterion changed.

## Evidence selection and diagnostics

The first fresh curated pass is preserved under `seed-{0,1,2}/`. It produced
38/39 ordinary passes. A temporary uncontextualized compliance probe produced
34/39 passes because its Judge input omitted the Scenario Goal and supplied
knowledge. The complete-context re-judge under `contextual-rejudge/` produced
38/39 passes: seeds 1 and 2 were 13/13; seed 0 was 12/13.

The remaining seed-0 `j1-card-switch-stale-options` Episode had both a genuine
invented payment-history claim and premature confirmation. It is retained as
diagnostic evidence and excluded from the passing N=3 set. The first bounded
replacement under `reverify-seed-0/` passed the ordinary verdict and the timing
and persistence criteria. Its complete-context ruling at
`contextual-rejudge/reverify-seed-0.json` passed all three compliance criteria;
this is the selected seed-0 Episode. A second already-started bounded attempt is
preserved under `reverify-seed-0-attempt-2/` but is not selected.

The selected curated evidence is therefore:

- repetition 0: the 12 passing `seed-0/` Episodes plus
  `reverify-seed-0/j1-card-switch-stale-options.json`, with complete-context
  rulings from `contextual-rejudge/seed-0.json` for the 12 and
  `contextual-rejudge/reverify-seed-0.json` for the replacement;
- repetitions 1 and 2: all 13 Episodes in `seed-1/` and `seed-2/`, with rulings
  in `contextual-rejudge/seed-1.json` and `seed-2.json`;
- pilot: the rejected Qualification's defects-off repetition 1, re-judged at
  `contextual-rejudge/pilot-cell-defects-off-1.json`.

The pilot grounding ruling explicitly classified the customer's uncertainty
about which option corresponds to “whole bill” as a concept/label issue rather
than an unsupported account-state claim. This resolves the N-007 scope defect.
