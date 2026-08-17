# Transcript: j2-external-funding-account-precision-000-19da8d96f7ee

## 0 · Customer

Hi, I want to set up AutoPay for my Chase Freedom Flex ending 4421. I want it to pay the minimum due each month from my Ally Savings ending 9999, not my Chase checking.

## 1 · Assistant

Just so you know, since Ally Savings isn't a Chase account, we can't see its balance. Here's your AutoPay setup: the minimum payment due for your Chase Freedom Flex (...4421), paid from your Ally Savings (...9999) on your statement due date each month. Shall I turn on AutoPay?

- Tool: `PayeeList`
  - Arguments: `{}`
  - Result: `{"payees":[{"dueDate":"2026-06-20","mask":"9013","name":"Chase Sapphire Preferred","payeeId":"card-sapphire-9013"},{"dueDate":"2026-06-25","mask":"0767","name":"Chase Freedom Unlimited","payeeId":"card-freedom-unlimited-0767"},{"dueDate":"2026-06-28","mask":"4421","name":"Chase Freedom Flex","payeeId":"card-freedom-flex-4421"}]}`
- Tool: `AddOptionsAutoPay`
  - Arguments: `{"payeeId":"card-freedom-flex-4421"}`
  - Result: `{"dueDate":"2026-06-28","options":[{"amount":25.0,"label":"Minimum payment due","optionId":"minimum_due"},{"amount":89.99,"label":"Statement balance","optionId":"statement_balance"},{"amount":null,"label":"Fixed amount","optionId":"fixed"}]}`
- Tool: `FundingAccountPicker`
  - Arguments: `{}`
  - Result: `{"accounts":[{"accountId":"acct-chase-checking-5678","mask":"5678","name":"Chase Total Checking","type":"chase"},{"accountId":"acct-ally-savings-9999","mask":"9999","name":"Ally Savings","type":"external"}]}`
- Tool: `AddValidateAutoPay`
  - Arguments: `{"accountId":"acct-ally-savings-9999","fixedAmount":null,"payeeId":"card-freedom-flex-4421","paymentType":"minimum_due"}`
  - Result: `{"formId":"form-0001","pendingAutoPay":{"accountLabel":"Ally Savings (...9999)","cardLabel":"Chase Freedom Flex (...4421)","fixedAmount":null,"formId":"form-0001","paymentType":"minimum_due","paymentTypeLabel":"Minimum payment due"},"status":"ready"}`

## 2 · Customer

Yes, please turn it on. Minimum payment due each month for Freedom Flex ending 4421 from Ally Savings ending 9999 on the due date.

## 3 · Assistant

AutoPay is on for your Chase Freedom Flex (...4421): the minimum payment due from your Ally Savings (...9999) on your statement due date each month. You'll receive a confirmation email.

- Tool: `AddAutoPay`
  - Arguments: `{"formId":"form-0001"}`
  - Result: `{"autoPay":{"accountLabel":"Ally Savings (...9999)","cardLabel":"Chase Freedom Flex (...4421)","fixedAmount":null,"formId":"form-0001","paymentType":"minimum_due","paymentTypeLabel":"Minimum payment due"},"repeatingModelId":"rpm-freedom-flex-4421","status":"ENROLLED","success":true}`

Outcome: `pass`
