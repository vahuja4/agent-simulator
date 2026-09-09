# What the mock agent is for, and what admission does and does not prove

Written 2026-09-09 while landing the J1 intent gate (recovery plan Phase 1
step 1). Plain-language companion to `CONTEXT.md`; the vocabulary is the
glossary's.

## What the harness is for

The harness tests a customer-facing payment assistant, the agent-under-test.
A simulated user plays a Persona toward a Goal, the Agent adapter carries each
message to the agent and brings back its reply and Trace, and the Verdict is
decided in two layers: deterministic Assertions gate LLM Judge rulings. A
Scenario is run over several Seeds and reported as a Pass rate.

## The problem the mock solves

Before the harness can grade a real agent, the harness itself has to be
right. If a Judge rules "the agent skipped confirmation", that is either a
real failure or a bad ruling, and testing against the real agent cannot tell
them apart, because nobody knows in advance what the real agent will do. The
harness needs an agent whose behavior is known exactly.

## What the mock is

`MockPayCardAgent` under `agentsim/adapters/mock_paycard/` is a hand-written,
deterministic stand-in for the assistant. It contains no LLM, the same input
always yields the same output, and a conversation replays on a laptop in
milliseconds. It is the harness's answer key, used three ways:

- **A clean reference.** With every defect switch off it is meant to be a
  correct agent. A failure against the clean mock is a harness bug or a mock
  bug, never an agent bug. Mock bugs are recorded as M-series entries in
  `docs/ledgers/mock-findings.md` and fixed only under the AGENTS.md
  mock-change approval.
- **A defect generator.** Seven planted defects, D1 through D7, each sit
  behind a switch: submit without confirmation, stale options after a card
  switch, claiming success on a failed submit, and so on. Switch one on and
  the Judges must catch it; switch it off and they must not. That pairing is
  how criteria wording is calibrated.
- **The admission gate for synthesized Scenarios.** A Candidate is admitted
  only if its Qualification passes against the clean mock (defects off) and
  catches its Fitness target with the defect on. The mock is the yardstick
  every generated Scenario is measured against.

## Why a mock bug matters so much

Because the mock is the yardstick, a mock bug becomes a false Verdict. M-019
is the worked example: the clean mock staged a payment the customer never
chose, so a sound Candidate failed Qualification, was rejected, and consumed
its Coverage cell's regeneration budget. Six of nine defects-off Episodes
for that cell were the mock's fault, not the Scenario's and not the
simulator's. Fixing the mock does not improve the real agent; it makes the
harness's judgments about the real agent trustworthy and unblocks the
synthesis pipeline.

## Why the mock stays deterministic and LLM-free

With an LLM inside, the same conversation could go two ways, the defect
on/off comparison would stop being a controlled experiment, and no mock
finding would be replayable. So when the mock cannot tell what the customer
means, the rule is to ask, never to guess: a question is answered, a negated
card is not a switch target, and a noisy message is reflected back and
applied only once confirmed. See `docs/solutions/j1-intent-gate.md`.

## The objection: "the harness may behave differently against a live agent"

It will, and that is expected. The honest position is that Admission is a
necessary check, not a sufficient one.

**What Admission proves.** Properties of the Scenario and the harness that do
not depend on which agent is being tested: the Goal is reachable in the
Fixture state, the Complication actually appears in conversation, the
simulated user stays in character, and the Judges pass a correct agent and
catch the planted defect. The Scenario carries these properties with it.

**What Admission does not prove.** The conversation itself will differ. The
simulated user is an LLM reacting to whatever the agent says, so a live agent
that asks for the date before the amount, or confirms in different words,
produces a Transcript the mock never produced. Admission cannot preview that.

**Why that is acceptable.** The harness grades outcomes and actions, not
scripts. Judges read the Transcript together with the Trace: was a payment
validated before it was submitted, does the reply match what the tools did
(Say/do consistency), was the customer told the truth. Those answers do not
depend on wording. Scenarios are distributions run over several Seeds, so one
odd conversation decides nothing. Reported runs use Model-family separation
between simulated user and Judge.

**Where the objection has teeth.** Two ways the switch to a live agent can
fool the harness:

1. *Criteria tuned to the mock's style.* If a Judge criterion quietly expects
   the mock's exact behavior, say a clarifying question at a particular point,
   a live agent that simply understood the customer could be marked down. The
   guard is that every criterion wording change must be live-verified before
   its phase closes, and that defects-off false alarms are tracked as a
   first-class number. That guard has so far been exercised only against the
   mock.
2. *Journey shape.* The mock encodes one design of each Journey: card, then
   account, then amount, then date. A live agent with a different but valid
   order could trip an Assertion that assumes the mock's order. That would be
   a harness bug, and it would surface as false alarms in the first live run.

**The sufficient check.** Phase 5 live runs of the admitted library against
the real agent, with the Judge and simulated user from different model
families, where false alarms against a clean live agent are the number to
watch. If they cluster on one criterion, that criterion was overfit to the
mock: reword it, live-verify it, and re-qualify. That loop is the design. Work
on the mock makes the first half of the loop trustworthy; it does not stand in
for the second half.
