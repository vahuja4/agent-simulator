# Mock and harness findings ledger

| ID | Date | Finding | Detection | Resolution / guard |
|---|---|---|---|---|
| M-001 | 2026-08-26 | The Fitness-target applicability contract was under-specified relative to deterministic mock reality: D4 needs active enrollment, a defined minimum due, and a representable below-minimum fixed amount; D6 needs a scheduled AutoPay payment, not merely an enrollment. | Caught in review during the d4/d6 contract session; that session corrected the contract but did not log the finding. | Corrected in `b5cc0a2`; `test_data_gated_fitness_targets_declare_fixture_applicability` mechanically preserves the required predicates. No mock behavior changed. |
