---
title: The probe command plays ordinary Episodes without the Run's machinery; a harness failure inside a climb aborts it rather than becoming an Episode error
category: journey-harness
symptoms:
  - A session wires `probe` through `BatchRunner` so a Probe gets a manifest too, and ends up with two records that can disagree about the same Episode.
  - A `play` that raises is recorded as an Episode `error`, so a climb that fell over is reported as a Rung the agent did not survive.
  - Probe Episodes are written under `journey_runs/`, where a Run's summary can count them.
  - A Probe's Episode directory has no `trace.json`, `transcript.md` or `run.json` and a session treats it as half-written.
  - A session adds `journey_probes/` to `.gitignore`, and the evidence a suspected finding rests on is never committed.
---

# The probe command plays ordinary Episodes without the Run's machinery

## Question

`climb` owns the decision and is handed a `play(rung, seed)`; `run_command`
already joins Scenarios, adapter, Simulated user and Judge into Episodes. How
much of `run_command` should `probe_command` be — and what does a Probe leave
behind, given that its output is the evidence a suspected finding rests on?

## Decision

- **`play` is `run_episode` then `evaluate_episode`, and nothing else.** No
  `BatchRunner`, no manifest, no `BatchRunSpec`. Nothing about a Rung reaches
  either function: they see a Synthesized Journey Scenario like any other, which
  is the whole point of a Rung realizing one. The climb record is the only
  record of the loop, so no second account of the same Episode exists to drift.
- **A Probe's Episode directory is exactly what those two functions write** —
  `scenario.yaml`, `transcript.jsonl`, `episode.json`, `raw_trace.json`,
  `normalized_trace.json`, `evaluation.json`. A Run's extra `trace.json`,
  `transcript.md` and `run.json` come from `BatchRunner`, not from the Episode.
- **A harness failure inside `play` aborts the climb.** In a Run, a Simulated
  user that cannot be built is that Scenario's `error` and the next Scenario
  still runs. In a climb there is no Episode to call unreadable: nothing was
  played, so the record is marked `aborted`, keeps every Rung already finished,
  and `broke_at` stays null. Adapter and Simulated-user failures *during* a
  conversation are unaffected — `run_episode` makes those stop reasons, so they
  become an `error` Verdict and an inconclusive Rung, as ADR 0008 says.
- **Episodes go under `journey_probes/<probe_id>/rungs/rung-<n>/seed-<m>/`.**
  CONTEXT.md's "a Run never contains Probe Episodes" starts with them not being
  written where a Run's are.
- **`journey_probes/` is not git-ignored, unlike `journey_runs/`.** A
  development Run is not evidence; a Probe's Episodes are the evidence ADR 0008's
  third condition requires a human to read before a finding counts.
- **The climb record names the break and points at it, and does not restate
  it.** Each Seed entry carries its Episode directory, relative to the Probe
  directory, and the source, id, turn and message of each failed check. The
  evidence itself stays in that Episode's `evaluation.json`.
- **Refused before the first write:** a set realizing no Ladder or more than
  one, a set missing a Rung, repeated Seeds, a taken Probe id. Exit 2, as the
  other commands use it.

## Why

Everything a Run's machinery adds is about a Run's question — a Pass rate over a
set, resumable per-Scenario accounting, clustering. A Probe asks a different
question and answers it from `climb.json`, so a manifest would be a second
record with no reader, and two records of one Episode is how they come to
disagree.

Aborting on a raise rather than absorbing it follows from what the climb reports.
Its output is *how far the agent climbed*; an error it swallowed would raise the
Rung count without an Episode behind it, and a Rung that was never played must
never look like one the agent did not survive.

## What would make us revisit it

- A Probe grows long enough that resuming a half-finished climb matters. Then
  the manifest question comes back, and the answer is resumption in `climb`,
  which already writes its record Rung by Rung — not a `BatchRunner` beside it.
- Findings are reviewed often enough that reading `transcript.jsonl` is the
  friction. Then render a transcript into the Episode directory at the end of a
  Probe; it is derived from what is already there.
- Probe directories become large enough to be a burden in Git. The answer is a
  rule about which Probes are kept, not ignoring the evidence.
