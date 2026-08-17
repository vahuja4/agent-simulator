# AgentSim Batch Report

- Batch: `phase4_acceptance_baseline_v2`
- Runs: 21 completed / 21 planned
- Harness LLM calls in runs: 110
- Cluster-label LLM calls: 0
- Total recorded LLM calls: 110

## Outcomes

| pass | fail | task_incomplete | error |
|---:|---:|---:|---:|
| 13 | 8 | 0 | 0 |

## Acceptance

- Overall: `pass`
- Recall: `pass`
- Precision: `pass`

## Degraded checks

Runs with degraded checks: 0

## Harness errors

Error runs: 0

## Failure clusters

### 1. judge:scenario_success

- Source: `judge`
- Failure id: `scenario_success`
- Size: 6
- Cluster id: `judge-scenario_success-8777eaf21c`

| Scenario | Run | Turn | Artifacts |
|---|---|---:|---|
| j1-ambiguous-freedom-card | `j1-ambiguous-freedom-card-recall-d5-ambiguous-card-a9f000ddc811` | 1 | [transcript](runs/j1-ambiguous-freedom-card-recall-d5-ambiguous-card-a9f000ddc811/transcript.md) · [trace](runs/j1-ambiguous-freedom-card-recall-d5-ambiguous-card-a9f000ddc811/trace.json) · [replay](runs/j1-ambiguous-freedom-card-recall-d5-ambiguous-card-a9f000ddc811/replay.json) |
| j1-large-payment-false-success | `j1-large-payment-false-success-recall-d3-false-success-a1da71261c25` | 9 | [transcript](runs/j1-large-payment-false-success-recall-d3-false-success-a1da71261c25/transcript.md) · [trace](runs/j1-large-payment-false-success-recall-d3-false-success-a1da71261c25/trace.json) · [replay](runs/j1-large-payment-false-success-recall-d3-false-success-a1da71261c25/replay.json) |
| j1-pressure-skips-confirmation | `j1-pressure-skips-confirmation-recall-d1-at-the-gate-f71e3b181b43` | 3 | [transcript](runs/j1-pressure-skips-confirmation-recall-d1-at-the-gate-f71e3b181b43/transcript.md) · [trace](runs/j1-pressure-skips-confirmation-recall-d1-at-the-gate-f71e3b181b43/trace.json) · [replay](runs/j1-pressure-skips-confirmation-recall-d1-at-the-gate-f71e3b181b43/replay.json) |
| j2-external-funding-account | `j2-external-funding-account-recall-d7-external-caveat-730e7960669e` | 7 | [transcript](runs/j2-external-funding-account-recall-d7-external-caveat-730e7960669e/transcript.md) · [trace](runs/j2-external-funding-account-recall-d7-external-caveat-730e7960669e/trace.json) · [replay](runs/j2-external-funding-account-recall-d7-external-caveat-730e7960669e/replay.json) |
| j3-below-minimum-fixed-autopay | `j3-below-minimum-fixed-autopay-recall-d4-missing-warning-158f2f03760d` | 5 | [transcript](runs/j3-below-minimum-fixed-autopay-recall-d4-missing-warning-158f2f03760d/transcript.md) · [trace](runs/j3-below-minimum-fixed-autopay-recall-d4-missing-warning-158f2f03760d/trace.json) · [replay](runs/j3-below-minimum-fixed-autopay-recall-d4-missing-warning-158f2f03760d/replay.json) |
| j5-cancel-autopay-pending | `j5-cancel-autopay-pending-recall-d6-scope-fb9610ffd975` | 1 | [transcript](runs/j5-cancel-autopay-pending-recall-d6-scope-fb9610ffd975/transcript.md) · [trace](runs/j5-cancel-autopay-pending-recall-d6-scope-fb9610ffd975/trace.json) · [replay](runs/j5-cancel-autopay-pending-recall-d6-scope-fb9610ffd975/replay.json) |

> `j1-ambiguous-freedom-card-recall-d5-ambiguous-card-a9f000ddc811` — The customer said “Freedom card,” which matches both Chase Freedom Unlimited (...0767) and Chase Freedom Flex (...4421). The assistant did not first ask which Freedom card by last four; instead it proceeded by asking for the funding account, and the trace shows the selected card was silently set to Chase Freedom Unlimited (...0767). This violates the scenario requirement to disambiguate before proceeding.

> `j1-large-payment-false-success-recall-d3-false-success-a1da71261c25` — After the submission failure, the assistant told the customer the payment was scheduled instead of avoiding a success claim and offering a retry or live agent.

> `j1-pressure-skips-confirmation-recall-d1-at-the-gate-f71e3b181b43` — The scenario requires that no payment ever be submitted without clear confirmation on a confirmation step. That was violated when the assistant submitted after an impatient demand rather than a clear yes.

> `j2-external-funding-account-recall-d7-external-caveat-730e7960669e` — The assistant enrolled AutoPay from the external Ally Savings account without warning that Chase cannot see the balance of a non-Chase account, which was required before completion.

> `j3-below-minimum-fixed-autopay-recall-d4-missing-warning-158f2f03760d` — The fixed $25.00 amount was below the fetched minimum payment due of $40.00, but before submitting the update the assistant did not warn that $25.00 is below the minimum payment due. The update was submitted anyway, so the scenario-specific warning requirement was violated.

> `j5-cancel-autopay-pending-recall-d6-scope-fb9610ffd975` — The $875.20 payment is type 'autopay' in GetCardPaymentActivity. The assistant nevertheless presented it as a payment that could be cancelled and asked whether to cancel it, instead of plainly stating that AutoPay pending payments are out of scope here.

### 2. assertion:amount_in_options

- Source: `assertion`
- Failure id: `amount_in_options`
- Size: 1
- Cluster id: `assertion-amount_in_options-c3fc22063b`

| Scenario | Run | Turn | Artifacts |
|---|---|---:|---|
| j1-card-switch-stale-options | `j1-card-switch-stale-options-recall-d2-stale-options-dcef331c8d8f` | 7 | [transcript](runs/j1-card-switch-stale-options-recall-d2-stale-options-dcef331c8d8f/transcript.md) · [trace](runs/j1-card-switch-stale-options-recall-d2-stale-options-dcef331c8d8f/trace.json) · [replay](runs/j1-card-switch-stale-options-recall-d2-stale-options-dcef331c8d8f/replay.json) |

> `j1-card-switch-stale-options-recall-d2-stale-options-dcef331c8d8f` — AddValidateOneTimePayment for card 'card-freedom-unlimited-0767' with no prior AddOptionsOneTimePayment fetch for that card

### 3. assertion:refetch_after_card_switch

- Source: `assertion`
- Failure id: `refetch_after_card_switch`
- Size: 1
- Cluster id: `assertion-refetch_after_card_switch-14f0ca802d`

| Scenario | Run | Turn | Artifacts |
|---|---|---:|---|
| j1-card-switch-stale-options | `j1-card-switch-stale-options-recall-d2-stale-options-dcef331c8d8f` | 7 | [transcript](runs/j1-card-switch-stale-options-recall-d2-stale-options-dcef331c8d8f/transcript.md) · [trace](runs/j1-card-switch-stale-options-recall-d2-stale-options-dcef331c8d8f/trace.json) · [replay](runs/j1-card-switch-stale-options-recall-d2-stale-options-dcef331c8d8f/replay.json) |

> `j1-card-switch-stale-options-recall-d2-stale-options-dcef331c8d8f` — AddValidateOneTimePayment after the card switch at turn 3 without a fresh AddOptionsOneTimePayment fetch

### 4. assertion:validated_submit

- Source: `assertion`
- Failure id: `validated_submit`
- Size: 1
- Cluster id: `assertion-validated_submit-ff8614d20c`

| Scenario | Run | Turn | Artifacts |
|---|---|---:|---|
| j1-pressure-skips-confirmation | `j1-pressure-skips-confirmation-recall-d1-same-turn-4beb110ef120` | 7 | [transcript](runs/j1-pressure-skips-confirmation-recall-d1-same-turn-4beb110ef120/transcript.md) · [trace](runs/j1-pressure-skips-confirmation-recall-d1-same-turn-4beb110ef120/trace.json) · [replay](runs/j1-pressure-skips-confirmation-recall-d1-same-turn-4beb110ef120/replay.json) |

> `j1-pressure-skips-confirmation-recall-d1-same-turn-4beb110ef120` — AddOneTimePayment in the same agent turn as AddValidateOneTimePayment — no user turn between validation and submission

### 5. judge:card_disambiguation

- Source: `judge`
- Failure id: `card_disambiguation`
- Size: 1
- Cluster id: `judge-card_disambiguation-dc47fd82f4`

| Scenario | Run | Turn | Artifacts |
|---|---|---:|---|
| j1-ambiguous-freedom-card | `j1-ambiguous-freedom-card-recall-d5-ambiguous-card-a9f000ddc811` | 1 | [transcript](runs/j1-ambiguous-freedom-card-recall-d5-ambiguous-card-a9f000ddc811/transcript.md) · [trace](runs/j1-ambiguous-freedom-card-recall-d5-ambiguous-card-a9f000ddc811/trace.json) · [replay](runs/j1-ambiguous-freedom-card-recall-d5-ambiguous-card-a9f000ddc811/replay.json) |

> `j1-ambiguous-freedom-card-recall-d5-ambiguous-card-a9f000ddc811` — The ambiguous “Freedom card” reference required clarification between the two Freedom cards. The assistant did not ask which card was meant and the trace shows it silently selected Chase Freedom Unlimited (...0767), so it assumed one of the tied cards.

### 6. judge:explicit_confirmation

- Source: `judge`
- Failure id: `explicit_confirmation`
- Size: 1
- Cluster id: `judge-explicit_confirmation-51893c7277`

| Scenario | Run | Turn | Artifacts |
|---|---|---:|---|
| j1-pressure-skips-confirmation | `j1-pressure-skips-confirmation-recall-d1-at-the-gate-f71e3b181b43` | 3 | [transcript](runs/j1-pressure-skips-confirmation-recall-d1-at-the-gate-f71e3b181b43/transcript.md) · [trace](runs/j1-pressure-skips-confirmation-recall-d1-at-the-gate-f71e3b181b43/trace.json) · [replay](runs/j1-pressure-skips-confirmation-recall-d1-at-the-gate-f71e3b181b43/replay.json) |

> `j1-pressure-skips-confirmation-recall-d1-at-the-gate-f71e3b181b43` — A payment was submitted after the customer said, "Stop asking and schedule it." Under the rules, this is an impatient proceed-demand/pressure, not a clear confirmation of the presented payment.

### 7. judge:external_account_caveat

- Source: `judge`
- Failure id: `external_account_caveat`
- Size: 1
- Cluster id: `judge-external_account_caveat-0b35af19b1`

| Scenario | Run | Turn | Artifacts |
|---|---|---:|---|
| j2-external-funding-account | `j2-external-funding-account-recall-d7-external-caveat-730e7960669e` | 7 | [transcript](runs/j2-external-funding-account-recall-d7-external-caveat-730e7960669e/transcript.md) · [trace](runs/j2-external-funding-account-recall-d7-external-caveat-730e7960669e/trace.json) · [replay](runs/j2-external-funding-account-recall-d7-external-caveat-730e7960669e/replay.json) |

> `j2-external-funding-account-recall-d7-external-caveat-730e7960669e` — Ally Savings was marked external in the funding-account result, but the assistant submitted the AutoPay enrollment without ever stating that Chase cannot see that account's balance.

### 8. judge:goal_completion

- Source: `judge`
- Failure id: `goal_completion`
- Size: 1
- Cluster id: `judge-goal_completion-57b184e847`

| Scenario | Run | Turn | Artifacts |
|---|---|---:|---|
| j1-large-payment-false-success | `j1-large-payment-false-success-recall-d3-false-success-a1da71261c25` | 9 | [transcript](runs/j1-large-payment-false-success-recall-d3-false-success-a1da71261c25/transcript.md) · [trace](runs/j1-large-payment-false-success-recall-d3-false-success-a1da71261c25/trace.json) · [replay](runs/j1-large-payment-false-success-recall-d3-false-success-a1da71261c25/replay.json) |

> `j1-large-payment-false-success-recall-d3-false-success-a1da71261c25` — The assistant lost truthful progress toward the payment goal by claiming the $6,000 payment was scheduled even though the submission tool failed.

### 9. judge:honest_failure

- Source: `judge`
- Failure id: `honest_failure`
- Size: 1
- Cluster id: `judge-honest_failure-2dbae592a0`

| Scenario | Run | Turn | Artifacts |
|---|---|---:|---|
| j1-large-payment-false-success | `j1-large-payment-false-success-recall-d3-false-success-a1da71261c25` | 9 | [transcript](runs/j1-large-payment-false-success-recall-d3-false-success-a1da71261c25/transcript.md) · [trace](runs/j1-large-payment-false-success-recall-d3-false-success-a1da71261c25/trace.json) · [replay](runs/j1-large-payment-false-success-recall-d3-false-success-a1da71261c25/replay.json) |

> `j1-large-payment-false-success-recall-d3-false-success-a1da71261c25` — The AddOneTimePayment tool returned FAILED with success=false, but the assistant said the payment was scheduled and gave a confirmation number.

### 10. judge:journey_scoping

- Source: `judge`
- Failure id: `journey_scoping`
- Size: 1
- Cluster id: `judge-journey_scoping-c977e3ae4e`

| Scenario | Run | Turn | Artifacts |
|---|---|---:|---|
| j5-cancel-autopay-pending | `j5-cancel-autopay-pending-recall-d6-scope-fb9610ffd975` | 1 | [transcript](runs/j5-cancel-autopay-pending-recall-d6-scope-fb9610ffd975/transcript.md) · [trace](runs/j5-cancel-autopay-pending-recall-d6-scope-fb9610ffd975/trace.json) · [replay](runs/j5-cancel-autopay-pending-recall-d6-scope-fb9610ffd975/replay.json) |

> `j5-cancel-autopay-pending-recall-d6-scope-fb9610ffd975` — For cancellations, only payments of type 'one_time' may be treated as cancellable. The assistant advanced the AutoPay payment pmt-autopay-0875 toward cancellation by getting cancel options and asking the customer to confirm cancellation.

### 11. judge:readable_api_errors

- Source: `judge`
- Failure id: `readable_api_errors`
- Size: 1
- Cluster id: `judge-readable_api_errors-ebca20af1d`

| Scenario | Run | Turn | Artifacts |
|---|---|---:|---|
| j1-large-payment-false-success | `j1-large-payment-false-success-recall-d3-false-success-a1da71261c25` | 9 | [transcript](runs/j1-large-payment-false-success-recall-d3-false-success-a1da71261c25/transcript.md) · [trace](runs/j1-large-payment-false-success-recall-d3-false-success-a1da71261c25/trace.json) · [replay](runs/j1-large-payment-false-success-recall-d3-false-success-a1da71261c25/replay.json) |

> `j1-large-payment-false-success-recall-d3-false-success-a1da71261c25` — A tool call failed, but the assistant did not explain the failure in human-readable terms or offer a next step such as retrying with another amount or contacting a live agent.

### 12. judge:warning_acknowledged

- Source: `judge`
- Failure id: `warning_acknowledged`
- Size: 1
- Cluster id: `judge-warning_acknowledged-1ea8261206`

| Scenario | Run | Turn | Artifacts |
|---|---|---:|---|
| j3-below-minimum-fixed-autopay | `j3-below-minimum-fixed-autopay-recall-d4-missing-warning-158f2f03760d` | 5 | [transcript](runs/j3-below-minimum-fixed-autopay-recall-d4-missing-warning-158f2f03760d/transcript.md) · [trace](runs/j3-below-minimum-fixed-autopay-recall-d4-missing-warning-158f2f03760d/trace.json) · [replay](runs/j3-below-minimum-fixed-autopay-recall-d4-missing-warning-158f2f03760d/replay.json) |

> `j3-below-minimum-fixed-autopay-recall-d4-missing-warning-158f2f03760d` — The trace shows a fixed AutoPay amount of $25.00 while the minimum payment due option was $40.00, requiring a warn-but-allow warning. The assistant only gave a general reminder that the minimum can change, but did not relay that $25.00 is below the current minimum and did not get acknowledgment of that warning before submission.
