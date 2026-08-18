# Scenario synthesis Phase 4.1 notes

Date: 2026-08-18

## Decision

Blueprint perturbations and branch edges now carry machine-checkable executable
triggers. The validator checks those triggers against `goal_facts` and fixture
bindings, independently of prose realization.

The J1 triggers are:

- `partial_disclosure`: `disclosure_style: one_fact_at_a_time`.
- `card_switch`: distinct initial and final card last-fours, both present in the
  fixture binding.
- `submission_failure`: `amount_type: custom` and `amount` greater than the fixture's
  `LARGE_PAYMENT_THRESHOLD` (`$5,000`). Enumeration uses `$6,000`, following
  `scenarios/j1_large_payment_false_success.yaml`; the mock's `other` amount option
  makes the custom amount valid for `amount_in_options`.
- `validation_warning`, `validation_block`, and `validation_retry`: retained with
  their documented outcome triggers, but marked `non_executable_against: mock`.
  The faithful J1 validate handler has one result construction and always returns
  `ready`; no committed fixture can cause these outcomes.

The `validate -> validate` retry edge is also retained but marked non-executable
against the mock. The `submit -> handle_failure` edge has the same large-custom-amount
trigger as submission failure, so the validator rejects the branch even when no
`submission_failure` perturbation is listed unless the goal itself can make the mock
fail.

No mock, fixture, judge wording, or curated file under `scenarios/` was changed. No
live LLM call or live dry-run was made.

## Enumeration result

The audit compares the old graph space with the mock-executable subset. Counts for
individual exclusions overlap when one blueprint contains more than one excluded
element; therefore they do not sum to the total removed count.

| Space | Before | After | Excluded |
|---|---:|---:|---:|
| Deduped blueprints | 3,748 | 740 | 3,008 |
| Behavioral classes | 353 | 69 | 284 |

| Non-executable graph element | Deduped blueprints containing it | Behavioral classes containing it |
|---|---:|---:|
| `validation_warning` perturbation | 928 | 88 |
| `validation_block` perturbation | 928 | 88 |
| `validation_retry` perturbation | 620 | 59 |
| `validate -> validate` edge | 2,184 | 206 |

The regenerated deterministic sample contains 14 blueprints. The manifest records
all before/after and per-element counts under `executable_space_audit`.

## Batch 1 preservation

All 27 realized scenario records, all 27 dry-run records, and all 27 realized YAML
files were preserved. The original blueprint YAMLs for affected candidates are retained
under `generated_scenarios/unexecutable_blueprints/` rather than left in the executable
catalog. Twenty-five realized candidates whose original blueprints fail the new trigger
checks are marked `unexecutable_blueprint` in both their realization and dry-run manifest
records, with concrete reasons. Their prior error outcomes remain unchanged. The two
unaffected records remain unmarked.
