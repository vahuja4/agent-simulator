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
