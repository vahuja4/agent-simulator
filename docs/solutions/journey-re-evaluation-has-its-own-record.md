---
title: A re-evaluation records its own progress, never in the Run's status
category: journey-harness
symptoms:
  - Session 08's `re_evaluate_command` set the Run record's `status` to `running` and `_play` wrote `aborted` there on an interrupt, so a Run whose conversations all finished read as aborted after an interrupted re-evaluation, and the next `--re-evaluate` kept it aborted for good ("the Run itself never finished").
  - `summarize` then told the reader the summary "covers only what ran" about a Run in which everything ran.
  - An interrupted re-evaluation also overwrote the Run's `ended_at` and `error`, losing the original abort error of a Run that really had aborted.
---

# A re-evaluation records its own progress, never in the Run's status

## Question

`run --re-evaluate` reuses `_play`, which finishes a Run record as `complete`
or `aborted`. Where does an interrupted re-evaluation write its abort, and how
does a later one know whether the conversations finished?

## Decision

- **Two facts, two fields.** `journey_run.json` `status`, `ended_at` and
  `error` are about the conversations and are written only by `run`. A
  re-evaluation writes its own `re_evaluation: {status: running | complete |
  aborted, started_at, ended_at, error}` entry (it replaced the bare
  `re_evaluated_at` timestamp) and never touches the Run's own three fields.
- **`_play` writes into whichever record it is handed** (`progress`): the Run
  record for `run`, its `re_evaluation` entry for `run --re-evaluate`. The
  earlier `finished` parameter — "keep an aborted Run aborted" — is gone
  because a re-evaluation no longer has the Run's status in its hands.
- **The report and `summarize` name an aborted re-evaluation apart** from an
  aborted Run: the conversations are as the Run left them; the Episodes the
  re-evaluation did not reach are counted as not finished (their manifest
  records were reset to `pending`) and keep their earlier `evaluation.json`;
  run `--re-evaluate` again.

## Why

One field cannot carry two facts that change at different times. The first
draft encoded "did the last re-evaluation finish" by overwriting "did the
conversations finish", and the only way to recover was to read the Run's
history, which nothing keeps. Keeping the Run's fields read-only for a
re-evaluation makes the recovery trivial (re-run it) and keeps the original
abort error of a Run that really aborted. Pinned by
`tests/test_journey_cli.py::test_an_interrupted_re_evaluation_does_not_make_a_finished_run_aborted`.

## What would make us revisit it

A need to keep more than the last re-evaluation (a history), or a
re-evaluation that replays conversations — then the entry becomes a list and
the second half of the split no longer holds.
