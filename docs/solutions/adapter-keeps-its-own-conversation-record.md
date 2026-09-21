---
title: The conversation adapter keeps its own record of acknowledged exchanges
category: journey-harness
symptoms:
  - The design note said that when Trace retrieval fails the normalized Trace's messages "come from the Transcript the harness recorded", but retrieve_trace(handle) is given no Transcript.
  - The note fixed the HTTP request timeout at 60 s and the Episode limit at 300 s, although one LangGraph turn makes several model calls at up to 30 s each with a retry.
  - The note's ConversationHandle had no place for the start response's agent kind, and AdapterError had no place for the service's own error code.
  - A failed action's raw record carries "result" null; deriving result_available from status would mark every controlled-tool-failure Episode partial and so error.
---

# The conversation adapter keeps its own record of acknowledged exchanges

## Question

Session 05a built the conversation lifecycle (`agentsim/adapters/conversation.py`)
and the journey service adapter (`agentsim/adapters/journey_service.py`).
`retrieve_trace` must never raise for a service-side problem and must still
return real messages when retrieval fails. Where do those messages come from:
does the caller pass its Transcript in, or does the adapter remember what it
sent and received?

## Decision

The adapter remembers. Per conversation it holds every exchange the service
acknowledged — the service's message ids, role, text — plus the texts of sends
that raised and the `tool_failures` it sent. `retrieve_trace(handle)` keeps its
signature. The record is dropped at `release`, so retrieve comes first.

Taken with it:

- Record messages have `sequence: None`: the service's one counter across
  messages and actions lives only in the Trace, and a position in a list is
  not that counter. So a fallback Trace is `messages: partial` (`unavailable`
  when the record is empty), `actions: unavailable`. It can never reach the
  Judge or pass an Assertion, which is right: it exists so something is saved.
- A send that raised is counted in a reason, never carried as a message: the
  adapter does not know whether the service recorded it (`400`/`409` do not,
  `500 agent_error` does, a timeout might have).
- When retrieval succeeds the record only *flags* the raw Trace
  (`messages: partial` on disagreement); the raw Trace is still what is
  normalized. A raw user message matching an unacknowledged send is not a
  disagreement — that is exactly what `500 agent_error` leaves behind.
- An unusable payload (wrong `trace_version`, no `events`, another
  conversation's id or Fixture hash) is returned as `raw` and nothing is read
  from it.
- `result_available` is "the raw action carries the `result` key". AGENT
  writes `"result": null` for a failed action; that is complete evidence.
- `reply_message_id: null` is a recorded fact, not a gap. Such a Trace is
  `available` and `to_trace()` refuses it; it only arises with stop reason
  `adapter_error`, which is `error` before the Judge is reached.
- `AdapterError(kind, detail, status, code)` with `agent_fault` true only for
  `service` + `agent_error`. `ConversationHandle` gains `agent`. The request
  timeout is a parameter defaulting to 120 s; the Episode limit becomes a
  parameter defaulting to 600 s in session 05b.

## Why

It is the smaller change: no Transcript type crosses the adapter interface
(the Transcript does not exist until session 05b), and the adapter is where
the service's ids are actually observed — the Transcript would only be a copy
of what the adapter returned. It also keeps "messages the adapter did not
observe are never invented" checkable in one module.

## What would make us revisit it

- A second `ConversationAdapter` implementation that cannot hold state between
  calls (a stateless client, or one process starting and another retrieving):
  then the record has to travel, and the Transcript is the natural carrier.
- A platform whose replies carry an ordering counter: the record could then
  hold real sequences and a fallback could be `messages: available`.
- The pinned raw Traces under `tests/fixtures/journey_agent_raw_traces/` catch
  drift only from the HARNESS side. AGENT changing its raw Trace format is
  caught when someone re-captures them (the cross-repository check in the
  session 05a prompt). `make test` cannot import AGENT, so this stays manual.
