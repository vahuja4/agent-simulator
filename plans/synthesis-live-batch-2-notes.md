# Scenario synthesis live batch 2 notes

Date: 2026-08-18

## First attempt

The first live-batch-2 realization was stopped after it damaged the restored batch-1
state. That uncommitted damage was discarded before Phase 4.2. The retained Step 1
finding was that realization needed additive reuse and preservation semantics, with
existing-file collisions failed closed rather than overwritten.

## Second attempt — Step 1 realization

The live realization entry point completed, but the result did not meet the expected
gate, so Step 2 was not run and no candidate was retried or edited.

End-of-run summary:

- realized: 9
- reused: 2
- retried: 1
- failed: 3
- preserved: 22

Outcome breakdown:

- 8 new candidates succeeded on the first LLM attempt.
- 1 new candidate (`j1-0e52ad6a51d58f25`) succeeded after one retry.
- 2 valid overlaps (`j1-633947b18615197d` and `j1-61c4ef0cacdc2b41`)
  were reused without an LLM call.
- 3 overlaps (`j1-6fd3cce8c9eff872`, `j1-82b14c01dcd19612`, and
  `j1-af21746358a09ca6`) failed closed with zero LLM attempts because an existing YAML
  was not reusable and was not overwritten.

This is a preservation failure relative to the batch gate. Those three candidates
were among the 25 batch-1 records marked `status: unexecutable_blueprint`, which were
required to remain untouched. Their realization records are now instead marked
`status: failed_closed`, leaving only 22 records marked `unexecutable_blueprint`.
The manifest contains 36 realization records in total: 22 preserved marked records,
2 reused valid records, 9 newly realized records, and 3 failed-closed records.

The first sandboxed invocation could not resolve the API host and exited with
`APIConnectionError` before receiving a model response. The same authorized entry
point was then run with network permission; the counts above are from that completed
run.

## Step 2

Not run. The live dry-run gate remains pending because Step 1 failed.

## Step 2 completion

Phase 4.4 selection-gate verification resolved exactly 14 records for
`live-batch-2`, representing 14 unique blueprint IDs. The authorized dry-run entry
point was invoked once. It returned normally after recording both configurations
for every candidate, but all 28 conversations failed before judge evaluation with
`OpenAIError: Missing credentials. Please pass an api_key, workload_identity,
admin_api_key, or set the OPENAI_API_KEY or OPENAI_ADMIN_KEY environment variable.`
No candidate was edited, deleted, or re-run.

Recorded outcomes:

- Solvable rate: 0/14 (0%) faithful `agent_pass`.
- `simulator_invalid`: 0. There are no compliance-judge reasons; compliance was
  `not_evaluated` for every run because the missing-credentials error occurred first.
- Defect-sensitive rate among targeted runs: 0/14 (0%).
- Error count: 28 total, comprising 14 faithful errors and 14 targeted-defect errors.

All 14 faithful runs failed and are findings:

- `j1-82b6ebb15f31ae4b`
- `j1-0fb64fdd31e1862d`
- `j1-d4005d61d5c1c541`
- `j1-225595457f4c793b`
- `j1-2484e5f390c4919e`
- `j1-e0eb0744f28a9653`
- `j1-535fdfa16315d879`
- `j1-a4731cb8613f3514`
- `j1-d9c5a7d33bdea7c0`
- `j1-25ec15d058329ba8`
- `j1-33a8542037f90a65`
- `j1-43d6711c9d6ab035`
- `j1-3d88f3176efb27cd`
- `j1-e5b543fbe1a2edeb`

Comparison with `live-batch-1`: batch 1 recorded 27 candidates and 54 errors (27
faithful plus 27 targeted-defect), with 0/27 solvable and 0/27 defect-sensitive.
Batch 2 likewise produced no evaluated outcome, but its failure mode differs: batch
1 recorded `APIConnectionError: Connection error.` for all conversations, whereas
batch 2 recorded a missing-credentials `OpenAIError` for all conversations.

## Step 2 authorized retry

After explicit follow-up authorization, the dry-run entry point was invoked once
more with `.env` exported into the process environment. This retry reached live LLM
evaluation, but the available API balance was exhausted partway through the batch.
The final nine conversations recorded `RateLimitError` with
`code: credit_balance_exhausted`: the targeted-defect run for
`j1-25ec15d058329ba8`, followed by both runs for `j1-33a8542037f90a65`,
`j1-43d6711c9d6ab035`, `j1-3d88f3176efb27cd`, and
`j1-e5b543fbe1a2edeb`. No further run was made.

Retry outcomes:

- Solvable rate: 7/14 (50%) faithful `agent_pass`.
- `simulator_invalid`: 0. There are no compliance-judge reasons; all 19 evaluated
  conversations were compliance-valid, while the nine quota errors were
  `not_evaluated`.
- Defect-sensitive rate among targeted runs: 9/14 (64.3%). Nine targeted runs were
  `agent_fail`; the remaining five were quota errors.
- Error count: 9 total, comprising four faithful errors and five targeted-defect
  errors.

Seven faithful runs did not pass and are findings:

- `j1-82b6ebb15f31ae4b`: `agent_fail`; the required initial card ending in 0767
  was not selected first.
- `j1-0fb64fdd31e1862d`: `agent_fail`; after accurately reporting submission
  failure and the customer choosing to stop, the assistant lost the thread and
  asked for a payment date.
- `j1-2484e5f390c4919e`: `agent_fail`; after the customer accepted the submission
  failure and chose to stop, the assistant revalidated and attempted to schedule
  the payment again.
- `j1-33a8542037f90a65`: quota error before evaluation.
- `j1-43d6711c9d6ab035`: quota error before evaluation.
- `j1-3d88f3176efb27cd`: quota error before evaluation.
- `j1-e5b543fbe1a2edeb`: quota error before evaluation.

Compared with `live-batch-1`, which recorded 0/27 solvable, 0/27
defect-sensitive, and 54 connection errors, the retry produced 19 evaluated
conversations and demonstrated both faithful success and targeted-defect
sensitivity before quota exhaustion. Because four faithful candidates and five
targeted runs were not evaluated, the retry rates are incomplete batch outcomes
rather than final acceptance rates.
