# CONTEXT.md — Shared Vocabulary

This file defines the project's domain language. Agents and humans use
these terms exactly as defined here — in code identifiers, file names,
docs, and conversation. If a decision changes a definition, update this
file in the same commit.

## Vocabulary

- **Scenario** — a declarative test situation: persona + goal + knowledge
  level + complication + max turns + judge criteria. Stored as a file;
  the unit of test authorship.
- **Persona** — who the simulated user is: background, temperament,
  communication style. Grounded top-down (from the scenario spec) and
  bottom-up (from what such a user would plausibly know).
- **Goal** — what the simulated user is trying to get done. The
  conversation succeeds or fails relative to the goal, not to any
  particular phrasing.
- **Knowledge level** — how much correct domain vocabulary and factual
  context the simulated user holds. Low knowledge means describing things
  in lay terms, possibly using terminology wrongly.
- **Complication** — the deliberate difficulty injected into a scenario:
  underspecification, mid-conversation correction, goal shift, multi-intent
  turn, false premise, out-of-scope drift, channel noise. One complication
  per scenario is the default; compound complications are their own
  scenarios.
- **Seed** — one stochastic realization of a scenario. Scenarios are
  distributions, not test cases; a scenario runs N seeds and reports a
  pass rate.
- **Run** — one execution of the full suite (or a filtered subset):
  scenarios × seeds, producing a set of transcripts and a results summary.
- **Episode** — one simulated conversation: a single scenario + seed
  played out between the simulated user and the agent-under-test.
- **Turn** — one user message and the agent's reply to it, including any
  tool calls attached to that reply.
- **Transcript** — the on-disk record of an episode: ordered turns, tool
  calls, termination reason, timing, model identifiers. JSONL,
  append-only, schema-stable. The contract between the runner and the
  judge pass.
- **Simulated user** — the LLM role-playing the persona toward the goal.
  Also: synthetic user.
- **Agent adapter** — the one-method interface to the agent-under-test:
  message in → reply + tool calls out, holding whatever session state the
  backend needs. Implementations: `MockAgent` (harness development),
  `SierraAgent` (headless API + trace fetch).
- **Trace** — the agent platform's record of what the agent did
  internally (tool calls, parameters, results). Fetched by the adapter
  and attached to turns so judges can see actions, not just words.
- **Termination** — the decision that an episode is over, and by whom:
  simulated user (goal reached / gives up), judge (halt on met/failed
  criterion), or harness (max turns). Termination reason is always
  recorded.
- **Judge** — an LLM evaluator from our existing judge infrastructure,
  applied to a transcript (or mid-episode via the judge hook). Judges are
  fail-closed: anything other than an explicit pass is a fail.
- **Judge criterion** — a single named check a judge applies, defined per
  scenario or globally. Example: goal completion, groundedness,
  say/do consistency.
- **Say/do consistency** — the check that what the agent *claimed* in
  text matches what the trace shows it *did*.
- **Verdict** — the final outcome for an episode, produced by the
  two-layer design: deterministic assertions act as a hard gate over LLM
  judge rulings. An episode passes only if both layers pass.
- **Assertion** — a deterministic, code-level check on the transcript or
  trace (no LLM involved). The first layer of the verdict.
- **Pass rate** — the fraction of seeds of a scenario whose episodes
  received a passing verdict. The reported unit of results.

## Invariants

1. **Zero new dependencies.** Stdlib plus what is already in the
   environment. If a task appears to need a new package, stop and ask.
2. **Adapter boundary.** All access to the agent platform goes through
   the agent adapter interface. No platform client code imported
   anywhere else.
3. **Judge reuse.** Judges come from the existing judge infrastructure.
   No inline judge prompts in harness code.
4. **Model-family separation.** The simulated user and judge must use
   different model families for reported runs. Development runs against the
   mock may share a family; see `AGENTS.md` for the deferred enforcement
   contract.
