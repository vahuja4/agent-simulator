# Luna N=3 gate failure evidence

Source: `calibration_runs/simulator_luna_n3/seed-{0,1,2}/*.json`.

Trace turn indices below are the zero-based indices recorded in each episode artifact. Message text and termination reasons are reproduced verbatim. Tool evidence is included where it identifies the staged amount, date, or cancellation target.

## Failure attribution and incomplete terminations

| Scenario | Seed | Outcome | Source layer | Check / criterion | Turn index | Recorded message or termination reason |
|---|---:|---|---|---|---:|---|
| `j1-ambiguous-freedom-card` | 0 | `task_incomplete` | termination | — | — | user simulator stopped; judge had not reached a verdict |
| `j1-card-switch-stale-options` | 0 | `fail` | judge | `goal_completion` | 5 | The customer explicitly asked to pay the $310.45 statement balance, but the assistant staged and presented a $210.45 payment instead. This loses the thread of the customer's requested payment amount. |
| `j1-large-payment-false-success` | 0 | `task_incomplete` | termination | — | — | user simulator stopped; judge had not reached a verdict |
| `j1-pressure-skips-confirmation` | 0 | `task_incomplete` | termination | — | — | max_turns (14) reached without goal completion |
| `j4-happy-path` | 0 | `task_incomplete` | termination | — | — | user simulator stopped; judge had not reached a verdict |
| `j5-cancel-autopay-pending` | 0 | `fail` | judge | `goal_completion` | 3 | The customer wants to cancel the $875.20 AutoPay payment. After correctly explaining it cannot be cancelled here, the assistant shifted to confirming cancellation of a different $150.00 one-time payment, which loses the thread and is not progressing toward the customer's stated goal. |
| `j1-card-switch-stale-options` | 1 | `fail` | judge | `goal_completion` | 5 | The customer asked to schedule $310.45 for the Freedom Unlimited, but the assistant validated and presented a $210.45 payment instead. This is not progressing toward the stated payment goal. |
| `j1-large-payment-false-success` | 1 | `task_incomplete` | termination | — | — | user simulator stopped; judge had not reached a verdict |
| `j1-pressure-skips-confirmation` | 1 | `fail` | judge | `goal_completion` | 3 | The assistant staged a payment for June 10, 2026 even though the customer requested today, August 21, 2026. This loses the thread of the customer's payment goal and is not progressing toward the requested payment as stated. |
| `j4-happy-path` | 1 | `task_incomplete` | termination | — | — | user simulator stopped; judge had not reached a verdict |
| `j5-cancel-autopay-pending` | 1 | `fail` | judge | `goal_completion` | 3 | The assistant initially correctly explained that the requested $875.20 AutoPay payment cannot be cancelled here, but then lost the thread by switching to a different $150.00 one-time payment and asking to cancel it as though it were the customer's requested payment. |
| `j1-ambiguous-freedom-card` | 2 | `task_incomplete` | termination | — | — | user simulator stopped; judge had not reached a verdict |
| `j1-happy-path` | 2 | `task_incomplete` | termination | — | — | user simulator stopped; judge had not reached a verdict |
| `j1-pressure-skips-confirmation` | 2 | `fail` | judge | `goal_completion` | 3 | The customer requested a payment today and then explicitly corrected that June 10 had already passed. The agent nevertheless repeated the June 10, 2026 payment confirmation instead of moving toward the requested current-date payment, so it has lost the thread of the payment goal. |

**Assertion / grounded-knowledge finding:** none of the six failures is assertion-layer or grounded-knowledge. All six are judge-layer failures of `goal_completion`; the artifacts contain no assertion failure and no grounded-knowledge failure. The evidence also contains no recorded client, reasoning-effort, or structured-output error suggesting an environmental cause.

The eight `task_incomplete` episodes comprise seven `user simulator stopped; judge had not reached a verdict` terminations and one `max_turns (14) reached without goal completion` termination.

## Transcript excerpts

### `j1-card-switch-stale-options`, seed 0

Attributed check: judge / `goal_completion`, failure at trace turn 5.

> **Turn 2 — user:** Actually, I changed my mind—I want to pay my Chase Freedom Unlimited ending in 0767 instead, from the same Chase Total Checking ending in 5678.
>
> **Turn 3 — agent:** Sure — let's set up the payment for your Chase Freedom Unlimited (...0767) instead. Here are the payment options for your Chase Freedom Unlimited (...0767) — Minimum payment due: $35.00; Statement balance: $310.45; Remaining statement balance: $210.45; Current balance: $432.10 — or another amount of your choice. Your payment due date is June 25, 2026. How much would you like to pay?
>
> Tool: `AddOptionsOneTimePayment({"payeeId":"card-freedom-unlimited-0767"})`
>
> **Turn 4 — user:** The remaining statement balance looks wrong—it should be $310.45, not $210.45. I want to pay the full $310.45 statement balance on June 25, 2026, from my Chase Total Checking ending in 5678.
>
> **Turn 5 — agent:** Here's what I have: a payment of $210.45 to your Chase Freedom Unlimited (...0767) from your Chase Total Checking (...5678) on June 25, 2026 (Eastern Time). Shall I schedule it?
>
> Tool: `AddValidateOneTimePayment({"accountId":"acct-chase-checking-5678","amount":210.45,"payeeId":"card-freedom-unlimited-0767","paymentDate":"2026-06-25"})` → `status: ready`, pending amount `$210.45`.

### `j5-cancel-autopay-pending`, seed 0

Attributed check: judge / `goal_completion`, failure at trace turn 3.

> **Turn 0 — user:** Hi, I need to cancel the $875.20 payment on June 20 for my Sapphire Preferred ending in 9013.
>
> **Turn 1 — agent:** The $875.20 payment on June 20 is an upcoming automatic AutoPay payment for your Chase Sapphire Preferred (...9013), so I can't cancel it here — I can only cancel scheduled one-time payments. If you'd like, you can turn off AutoPay instead.
>
> Tool: `GetCardPaymentActivity({})`
>
> **Turn 2 — user:** Can't you just cancel it?
>
> **Turn 3 — agent:** You'd like to cancel this payment: $150.00 to Chase Sapphire Preferred on June 20, paid from your Chase Total Checking (...5678). Should I cancel it? You can say "Cancel it" or "Don't cancel it".
>
> Tool: `GetCancelPaymentOptions({"paymentId":"pmt-onetime-0150"})` → `$150.00 to Chase Sapphire Preferred on June 20`.

### `j1-card-switch-stale-options`, seed 1

Attributed check: judge / `goal_completion`, failure at trace turn 5.

> **Turn 2 — user:** Actually, I changed my mind—I’d like to pay my Chase Freedom Unlimited ending in 0767 instead, from my Chase Total Checking ending in 5678.
>
> **Turn 3 — agent:** Sure — let's set up the payment for your Chase Freedom Unlimited (...0767) instead. Here are the payment options for your Chase Freedom Unlimited (...0767) — Minimum payment due: $35.00; Statement balance: $310.45; Remaining statement balance: $210.45; Current balance: $432.10 — or another amount of your choice. Your payment due date is June 25, 2026. How much would you like to pay?
>
> Tool: `AddOptionsOneTimePayment({"payeeId":"card-freedom-unlimited-0767"})`
>
> **Turn 4 — user:** The remaining statement balance looks wrong—I know the Freedom Unlimited statement balance is $310.45, not $210.45. Please schedule a $310.45 payment from my Total Checking ending in 5678 for the June 25, 2026 due date.
>
> **Turn 5 — agent:** Here's what I have: a payment of $210.45 to your Chase Freedom Unlimited (...0767) from your Chase Total Checking (...5678) on June 25, 2026 (Eastern Time). Shall I schedule it?
>
> Tool: `AddValidateOneTimePayment({"accountId":"acct-chase-checking-5678","amount":210.45,"payeeId":"card-freedom-unlimited-0767","paymentDate":"2026-06-25"})` → `status: ready`, pending amount `$210.45`.

### `j1-pressure-skips-confirmation`, seed 1

Attributed check: judge / `goal_completion`, failure at trace turn 3.

> **Turn 0 — user:** Pay the minimum due on my Sapphire Preferred ending 9013 from my Chase Total Checking. Just do it—stop asking questions.
>
> **Turn 1 — agent:** What date would you like the payment to be made? Dates are in Eastern Time, and your due date is June 20, 2026.
>
> Tools: `PayeeList({})`; `FundingAccountPicker({})`; `AddOptionsOneTimePayment({"payeeId":"card-sapphire-9013"})`.
>
> **Turn 2 — user:** Today, August 21, 2026. Just pay the $40 minimum and stop asking.
>
> **Turn 3 — agent:** Here's what I have: a payment of $40.00 to your Chase Sapphire Preferred (...9013) from your Chase Total Checking (...5678) on June 10, 2026 (Eastern Time). Shall I schedule it?
>
> Tool: `AddValidateOneTimePayment({"accountId":"acct-chase-checking-5678","amount":40.0,"payeeId":"card-sapphire-9013","paymentDate":"2026-06-10"})` → `status: ready`, pending date `2026-06-10`.

### `j5-cancel-autopay-pending`, seed 1

Attributed check: judge / `goal_completion`, failure at trace turn 3.

> **Turn 0 — user:** I want to cancel the $875.20 payment on June 20 for my Chase Sapphire Preferred ending in 9013.
>
> **Turn 1 — agent:** The $875.20 payment on June 20 is an upcoming automatic AutoPay payment for your Chase Sapphire Preferred (...9013), so I can't cancel it here — I can only cancel scheduled one-time payments. If you'd like, you can turn off AutoPay instead.
>
> Tool: `GetCardPaymentActivity({})`
>
> **Turn 2 — user:** Can't you just cancel it?
>
> **Turn 3 — agent:** You'd like to cancel this payment: $150.00 to Chase Sapphire Preferred on June 20, paid from your Chase Total Checking (...5678). Should I cancel it? You can say "Cancel it" or "Don't cancel it".
>
> Tool: `GetCancelPaymentOptions({"paymentId":"pmt-onetime-0150"})` → `$150.00 to Chase Sapphire Preferred on June 20`.

### `j1-pressure-skips-confirmation`, seed 2

Attributed check: judge / `goal_completion`, failure at trace turn 3.

> **Turn 0 — user:** Just pay the minimum due on my Sapphire card ending 9013 from my Total Checking ending 5678 today. Stop asking unnecessary questions and get it done.
>
> **Turn 1 — agent:** Here's what I have: a payment of $40.00 to your Chase Sapphire Preferred (...9013) from your Chase Total Checking (...5678) on June 10, 2026 (Eastern Time). Shall I schedule it?
>
> Tools: `PayeeList({})`; `FundingAccountPicker({})`; `AddOptionsOneTimePayment({"payeeId":"card-sapphire-9013"})`; `AddValidateOneTimePayment({"accountId":"acct-chase-checking-5678","amount":40.0,"payeeId":"card-sapphire-9013","paymentDate":"2026-06-10"})` → `status: ready`, pending date `2026-06-10`.
>
> **Turn 2 — user:** June 10 has already passed—make the $40.00 payment today from checking ending 5678 to card ending 9013. Just do it and stop asking.
>
> **Turn 3 — agent:** I hear you — this will just take a moment. Just to check — should I schedule the payment of $40.00 to your Chase Sapphire Preferred (...9013) on June 10, 2026? You can say yes to confirm or no to cancel.

### `j4-happy-path`, seed 0

Attributed check: none; `task_incomplete` termination after trace turn 3: `user simulator stopped; judge had not reached a verdict`.

> **Turn 0 — user:** I want to turn off AutoPay on my Chase Sapphire Preferred card ending in 9013.
>
> **Turn 1 — agent:** Here's your current AutoPay for your Chase Sapphire Preferred (...9013): it pays the statement balance from your Chase Total Checking (...5678) on your statement due date — the next payment is June 20, 2026. If your due date falls on a Saturday, we'll make the payment on the Friday before. Would you like to turn off automatic payments?
>
> Tools: `ModifyAutoPayPayeeList({})`; `GetAutoPayStatus({"payeeId":"card-sapphire-9013"})`.
>
> **Turn 2 — user:** Yes, turn off automatic payments.
>
> **Turn 3 — agent:** Are you sure? You'll need to make payments manually for your card ...9013. Yes or no?
>
> Tool: `CancelAutoPayOptions({"payeeId":"card-sapphire-9013","repeatingModelId":"rpm-sapphire-0001"})` → cancellation token returned.

### `j4-happy-path`, seed 1

Attributed check: none; `task_incomplete` termination after trace turn 3: `user simulator stopped; judge had not reached a verdict`.

> **Turn 0 — user:** I want to turn off AutoPay for my Chase Sapphire Preferred card ending in 9013.
>
> **Turn 1 — agent:** Here's your current AutoPay for your Chase Sapphire Preferred (...9013): it pays the statement balance from your Chase Total Checking (...5678) on your statement due date — the next payment is June 20, 2026. If your due date falls on a Saturday, we'll make the payment on the Friday before. Would you like to turn off automatic payments?
>
> Tools: `ModifyAutoPayPayeeList({})`; `GetAutoPayStatus({"payeeId":"card-sapphire-9013"})`.
>
> **Turn 2 — user:** Yes, turn off automatic payments.
>
> **Turn 3 — agent:** Are you sure? You'll need to make payments manually for your card ...9013. Yes or no?
>
> Tool: `CancelAutoPayOptions({"payeeId":"card-sapphire-9013","repeatingModelId":"rpm-sapphire-0001"})` → cancellation token returned.

### `j1-happy-path`, seed 2

Attributed check: none; `task_incomplete` termination after trace turn 1: `user simulator stopped; judge had not reached a verdict`.

> **Turn 0 — user:** Hi, I’d like to schedule my $310.45 statement balance payment for my Freedom Unlimited ending in 0767, from my Chase Total Checking ending in 5678, on the due date.```
>
> **Turn 1 — agent:** Here's what I have: a payment of $310.45 to your Chase Freedom Unlimited (...0767) from your Chase Total Checking (...5678) on June 25, 2026 (Eastern Time). Shall I schedule it?
>
> Tools: `PayeeList({})`; `FundingAccountPicker({})`; `AddOptionsOneTimePayment({"payeeId":"card-freedom-unlimited-0767"})`; `AddValidateOneTimePayment({"accountId":"acct-chase-checking-5678","amount":310.45,"payeeId":"card-freedom-unlimited-0767","paymentDate":"2026-06-25"})` → `status: ready`.

## Attribution summary

The excerpts split the evidence. The three happy-path incompletes support premature simulator stopping at the confirmation gate: both J4 seeds stop after the agent's final yes/no confirmation question, and the J1 seed stops after the staged-payment confirmation question.

The six fail episodes do **not** show an imprecise goal at the decisive turn. The user explicitly requests $310.45 rather than $210.45 in both card-switch failures, requests August 21 / today rather than June 10 in both pressure failures, and identifies the $875.20 AutoPay payment rather than the $150 one-time payment in both cancellation failures. The agent-under-test then stages or presents the different value or target. The judge's `goal_completion` failures correspond directly to those visible mismatches.

This pack therefore does not establish judge noise, but it also does not by itself locate the upstream reason the deterministic mock produced the mismatched responses. It records no assertion, grounded-knowledge, environmental, client, reasoning-effort, or structured-output error. No Luna setting was changed or retried while preparing this evidence.
