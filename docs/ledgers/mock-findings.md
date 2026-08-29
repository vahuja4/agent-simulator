# Mock and harness findings ledger

| ID | Date | Finding | Detection | Resolution / guard |
|---|---|---|---|---|
| M-001 | 2026-08-26 | The Fitness-target applicability contract was under-specified relative to deterministic mock reality: D4 needs active enrollment, a defined minimum due, and a representable below-minimum fixed amount; D6 needs a scheduled AutoPay payment, not merely an enrollment. | Caught in review during the d4/d6 contract session; that session corrected the contract but did not log the finding. | Corrected in `b5cc0a2`; `test_data_gated_fitness_targets_declare_fixture_applicability` mechanically preserves the required predicates. No mock behavior changed. |
| M-002 (M13 family) | 2026-08-26 | J1 ignores a stated amount correction after validation. It re-asks confirmation for the staged original amount and, after an affirmative, submits that stale amount. | Deterministic bounded probe against the defects-off mock; transcript below. | Resolved in `2f8e34b`: a changed stated amount, and the symmetric date correction, invalidates the staged form and is re-validated before confirmation. Guarded by `test_m002_post_validation_amount_correction_revalidates_and_submits` and `test_post_validation_date_correction_revalidates_and_submits`; the defect-toggle suite preserves both D1 shapes and all other planted behavior. |
| M-003 | 2026-08-29 | Qualification evidence validation compared resolved evidence paths with a relative bundle path, rejecting three complete live Episodes as duplicate or foreign; the interrupted pre-admission state would then rerun them instead of evaluating the retained bundle. | The first live low-Knowledge Qualification failed after writing all Episode evidence; a deterministic replay passed when only the artifact root changed from relative to absolute. | Resolved alongside the Task 5b evidence: validation normalizes artifact paths and complete pre-admission Qualification evidence resumes without invoking the runner. Guarded by `test_qualification_accepts_relative_output_root` and `test_qualification_resumes_after_evidence_write_before_admission`. No mock behavior changed. |
| M-004 | 2026-08-29 | A clean evidence commit changed repository revision/dirty snapshot metadata, causing reporting to invalidate the just-committed admission even though every semantic input was unchanged. A repeated `qualify` also derived a new run ID instead of following the Candidate terminal record. | Post-commit `build_coverage` reported zero admissions and one `qualification evidence identity or configuration mismatch`; the same bundle validated before commit. | Resolved after the Task 5b evidence commit: completed operations follow the terminal Qualification ID and historical admission validation permits repository-state drift while still requiring identical configuration, models, prompts, Fixture, and contracts. Guarded by `test_completed_qualification_survives_repository_state_change`; post-commit coverage validation reports one valid admission. No mock behavior changed. |

## M-002 probe transcript

M-002 is the worked example of the mock-findings process: bounded probe
finding → ledger entry → approval-gated fix → regression guards.

Defects-off `MockPayCardAgent`, conversation ID `post-validation-correction-probe`:

1. **User:** “Pay my Sapphire card.”
   **Mock:** asks for the funding account.
   **Tools:** `PayeeList({})`; `FundingAccountPicker({})`.
2. **User:** “From my checking account.”
   **Mock:** presents the Sapphire payment options, including statement balance `$875.20` and minimum due `$40.00`.
   **Tool:** `AddOptionsOneTimePayment({"payeeId":"card-sapphire-9013"})`.
3. **User:** “Pay the statement balance.”
   **Mock:** asks for the payment date.
   **Tools:** none.
4. **User:** “On the due date.”
   **Mock:** states `$875.20` and asks “Shall I schedule it?”
   **Tool:** `AddValidateOneTimePayment({"accountId":"acct-chase-checking-5678","amount":875.2,"payeeId":"card-sapphire-9013","paymentDate":"2026-06-20"})` → `{"status":"ready","formId":"form-0001","pendingPayment":{"amount":875.2,...}}`.
5. **User:** “Actually, make that $40 instead.”
   **Mock:** “Just to check — should I schedule the payment of $875.20 to your Chase Sapphire Preferred (...9013) on June 20, 2026? You can say yes to confirm or no to cancel.”
   **Tools:** none; no second `AddValidateOneTimePayment` occurs.
6. **User:** “Yes.”
   **Mock:** claims the `$875.20` payment was scheduled.
   **Tool:** `AddOneTimePayment({"formId":"form-0001"})` → `{"status":"SCHEDULED","success":true,"payment":{"amount":875.2,...}}`.

Observed classification: **(b)** — the mock re-asks confirmation and submits the original stale amount after “yes.”
