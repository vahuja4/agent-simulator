---
title: A Journey Run is a loop of single-Scenario batches, with its own Run record
category: journey-harness
symptoms:
  - BatchRunner(concurrency=1) handed every spec at once sequences Episodes through a semaphore inside asyncio.gather; when one task is interrupted, gather does not stop its siblings, and with doubles that never really suspend the remaining Episodes ran to the end after the "interrupt".
  - BatchRunner's manifest says pending, running or completed per Episode and nothing about the Run, so an interrupted Run could not be told from one still running, and AGENTS.md requires a record marked aborted.
  - Session 06 found that Judge and Assertion failure data carries per-Episode message and action ids, so the same failure in two conversations of different length would land in two clusters.
  - Coordinator pre-flight of the session 08 prompt found that cluster_failures reads only manifest.json and skips every outcome but fail, so task_incomplete Episodes would have been counted in the outcome table and listed nowhere.
  - The service contract has no operation that says which agent is answering, yet a Run against the stub must never be mistaken for a Run against the LangGraph agent.
---

# A Journey Run is a loop of single-Scenario batches, with its own Run record

## Question

Session 08 had to turn three finished pieces — `run_episode`,
`evaluate_episode`, and the payments `BatchRunner` / `cluster_failures` — into
the `run` and `summarize` commands without changing the payments modules. How
is a Run sequenced, what says a Run was aborted, what is clustering allowed to
see, and where does every non-`pass` Episode go in the report?

## Decision

- **Sequencing is a plain loop.** `run` calls `BatchRunner(concurrency=1,
  retry_errors=False).run([spec], execute)` once per Scenario. `BatchRunner`
  still owns the manifest, the per-Episode files and "an `execute` that raises
  is that Scenario's `error`". It never retries: `run_episode` refuses a
  directory that already holds an Episode.
- **The Run has its own record**, `journey_run.json`: written `running` before
  the first Episode, finished `complete` or `aborted` with the error. Anything
  other than `complete` is reported as aborted. It also holds the planned
  Scenario ids, so an aborted Run can name what it never started. An interrupt
  is recorded and then propagates as itself; a crash exits 1; exit 2 is only
  ever before the first write. A Run directory is never reused.
- **`--re-evaluate` reuses `BatchRunner` too.** It resets the manifest records
  it is about to evaluate to `pending` and runs an `execute` that only
  evaluates, so manifest, `run.json`, `trace.json` and `evaluation.json` are
  rewritten by the code that wrote them first. It makes the same
  `journey_sha256` / `fixture_state_sha256` check as `run`, before any write.
  An aborted Run stays aborted.
- **Clustering sees a copy of each failure without `message_ids` and
  `action_ids`** (`clustering_view`), and nothing else is removed: the relative
  evidence `files` stay. That copy is what `run` puts in the manifest;
  `evaluation.json` keeps the full record. `cluster_failures` is unchanged and
  called with its default threshold. Known consequence: with so few tokens per
  failure, one differing detail (another slot id, another stop reason) stays in
  the same cluster, and two differing details split it. That is the payments
  similarity rule doing what it does, not a Journey rule.
- **One report section per outcome**, so counted means listed: clusters for
  `fail` (one row per failure), `task_incomplete` grouped by the structured
  reason in `evaluation.json` `incomplete`, agent errors (`service` +
  `agent_error`) apart from infrastructure and harness errors, and "not
  finished" for an aborted Run. A `fail` Episode with no failure record — which
  evaluation never produces — would still be listed, under its own heading.
- **The agent kind comes from a probe conversation** (start, then release)
  made before anything is written. It doubles as the "service does not answer"
  refusal. Checked against AGENT's real stub service on 2026-09-21: it answers
  `stub`.
- **The Simulated user is built inside `execute`**, per Scenario, so a build
  failure is that Scenario's `error`. One is also built before the first write
  purely to surface missing configuration (`SimulatorConfigError` → exit 2);
  any other failure of that early build is ignored there and recorded when its
  Episode runs.

## Why

`gather` with a semaphore is sequential only while nothing goes wrong. The
AGENTS.md abort rule is about exactly the moment something does, and a loop
makes both "one at a time" and "an interrupt stops the Run" true by
construction instead of by scheduling. A test pins it: the runner is only ever
handed one spec.

The manifest could not carry the Run status without editing
`agentsim/types.py`, which the design note forbids, and `configuration` is
written once at creation. A separate file mirrors what synthesis already does
with `provenance.json` `status`.

Stripping only the ids follows the session 06 finding literally and keeps the
manifest record as close to `evaluation.json` as clustering allows. Dropping
the whole `evidence` block was considered: it makes every single-detail
difference split a cluster, which with Fixture ids varying by design across a
synthesized set would turn one systematic defect into a row of singleton
clusters.

## What would make us revisit it

- Parallel execution becomes a requirement: the loop goes, and interrupt
  handling has to be solved inside the batch, not around it.
- The first live Run shows clusters that are too coarse or too fine: tune what
  `clustering_view` keeps, or pass `cluster_failures` a threshold — do not fork
  its logic.
- The service contract gains a health or identity operation: replace the probe
  conversation with it.
- A second Journey needs different report sections (an outcome other than the
  four): the sections are keyed on the outcome classes `BatchRunner` allows.
