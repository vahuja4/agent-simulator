---
name: compound
description: "Run after completing any implement, debugging, or review task, before ending the session."
---

# Compound

Run this after completing any implement, debugging, or review task,
before ending the session.

Answer four questions. Act on each answer immediately — do not defer.

## 1. Did the agent do anything wrong that a rule would prevent?

Wrong pattern, violated harness invariant, misused vocabulary, touched
something it shouldn't. If yes: append ONE line to AGENTS.md stating
the rule as a prohibition or requirement. If the same rule already
exists, strengthen it instead of duplicating.

## 2. Did we settle a design question?

If a decision was made that a future session (or teammate) would
otherwise re-derive or contradict: write docs/solutions/<slug>.md with
frontmatter (title, category, symptoms) and four short sections — the
question, the decision, why, what would make us revisit it.

## 3. Did a term change meaning, or a new concept appear?

If yes: update CONTEXT.md in this same sitting. Definitions of
meaning, not implementation.

## 4. Does the M-, N-, or D-series ledger need an entry?

Any unplanted mock bug found (M), judge noise or ruling variance
observed (N), or planted defect added/changed (D): record it in the
ledger now, however small.

## 5. Would the system catch this failure automatically next time?

If the answer should be yes and isn't: write the test, assertion, or
check NOW — a mechanical check beats a written rule. Only fall back
to an AGENTS.md line if the check is genuinely not automatable.

## Anti-rationalization

| Excuse | Answer |
|---|---|
| "This is just a harness, not production" | The harness gates real release decisions; its bugs become false verdicts. |
| "I'll write the solutions doc after the next phase" | Undocumented decisions get re-litigated; write the four sections now, they take five minutes. |
| "The rule is obvious, no need to write it down" | It was violated this session, so it wasn't obvious. |
| "This finding is too small to record" | The M-series exists because small findings compound; one line in the ledger. |
| "Updating CONTEXT.md can batch with other changes" | Vocabulary that lags the code is how the last reconciliation took three passes. |
