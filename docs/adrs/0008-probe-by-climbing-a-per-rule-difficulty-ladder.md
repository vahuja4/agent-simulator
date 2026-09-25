# Probe for agent failures by climbing a per-rule difficulty ladder

The harness gains a second mode beside the measuring one. A Run measures: fixed
Scenarios, one Episode each, a Pass rate comparable between versions of the
agent-under-test. A Probe discovers: it attacks one named required rule of the
Journey definition and reports suspected findings with the evidence for each. A
Probe never reports a Pass rate, and a Run never contains Probe Episodes.

A Probe is an ordered series of Rungs against one required rule — a Ladder.
Rung 1 arranges the Fixture state condition under which that rule binds and
otherwise makes the Simulated user easy to deal with; each later Rung adds one
more Persona or Complication difficulty to the one before it. Every Rung is an
ordinary Episode played over N Seeds through the existing conversation
lifecycle, and it is clean only when it is clean across all of them. Code reads
the saved Verdicts between Episodes and decides whether to climb: a clean Rung
is survived and the next one runs, and the first Rung with a failed Assertion or
a Judge failure stops the Ladder. The result for a rule is the highest Rung
survived and the Rung that broke.

The Ladder is deliberately not an adaptive loop inside one conversation. On the
conversation lifecycle the Trace is retrieved only after the conversation ends,
so a Simulated user choosing its next move mid-Episode is choosing without the
evidence of what the agent did. Deciding between Episodes puts the decision
where the evidence already is. It also leaves Termination alone: every Rung ends
for one of the reasons the Simulated user and the harness already have, so
`SIMULATED_USER_STOP_REASONS` is not widened, no Episode ending is added, and
neither `episode.py` nor `evaluation.py` changes. A Probe that finds nothing
still reports how far the agent climbed, which a discovery mode otherwise cannot
say.

A suspected finding counts against the agent only when three things hold. The
Simulated user played fair: it used only what its Scenario gave it, stayed on
the Journey, and never did the agent's work for it. The Simulated user is one a
real business could receive: pushy, stubborn, confused and mistaken are all
fair, impossible is not. And the break is visible in the saved evidence: either
an Assertion failed, or the Judge failed a criterion and a human read the
Episode and agreed. A Judge failure alone is a lead, not a finding. Nothing is
confirmed by a machine — even a failed Assertion needs a human to rule out that
our own Simulated user caused it, which is a glance rather than a full read.

Playing fair is a condition on the Simulated user's messages, not on what the
harness knows. Whatever chooses and orders Rungs may read the Normalized Trace
in full; that is search guidance, and it no more invalidates a finding than a
coverage-guided fuzzer's crash. What the Simulated user may *say* is bounded by
the Sealed-world rule, and this ADR states the bound the rule left implicit: a
message must be one the Simulated user could have produced from its Scenario and
from what the agent has actually said to it. The Trace is never a source, and
Fixture state ids are not customer knowledge even though the Fixture state holds
them. Today `render_journey_knowledge` renders a grounded fact's value and never
its path, and the narrative Sealed-world check rejects a model-written field
carrying a token that is not a grounded fact; both already enforce this, and
neither may be relaxed for a Probe.

The Complication taxonomy is unchanged. ADR 0005 keeps its closed nine values
and its one-value-per-Scenario rule, because that rule exists to keep Coverage
cells finite rather than to limit how difficult a Simulated user may be. A Rung
carries several difficulties and is therefore never a Coverage cell, never a
Candidate, and never enters a Coverage count or denominator. A Rung is its own
committed input file naming the required rule it attacks, its position in the
Ladder, its primary Complication and the further difficulties it also carries;
it produces the Scenario that is played. A Probe never edits a committed
Scenario.

The decision recorded in
`docs/solutions/journey-simulated-user-fidelity-is-a-human-record.md` on
2026-09-21 stands unchanged. An earlier draft of this work had the Simulated
user check its own draft message and mark it when it failed, which is the
self-report field and deviation flag that decision rejected. The Ladder removes
the need: a Rung is written down and reviewed by a human before it is played, so
the judgement about whether an attack is fair happens before the Episode rather
than inside it. Simulated-user fidelity remains a human Spot-check record, and
no automated check of the Simulated user's conduct is added here.
