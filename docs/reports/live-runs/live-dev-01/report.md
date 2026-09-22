# Journey Run report: live-dev-01

- Journey: `appointment-rescheduling`
- Agent: `langgraph` at http://127.0.0.1:8765 (Episodes answered by: langgraph)
- Scenario set: `synthesized_journey_scenarios/appointment-rescheduling/live-dev-01` (4 Scenarios, one Episode each, run sequentially)
- Simulated-user model: `gpt-5.5` · Judge model: `gpt-5.5`
- Started 2026-09-22T02:50:08.933344Z, ended 2026-09-22T02:53:02.906156Z
- Judge calls: 4. The Simulated user's model calls are not recorded, so this is not a total.
- This report does not establish Judge accuracy, test quality or coverage: the Scenarios are validated, not Qualified, and the Judge prompt is uncalibrated.

**Simulated-user fidelity is not checked.** No check confirms that the Simulated user played each Scenario as written — its Persona, its Knowledge level (a specification here, not verified behavior), its Complication or its grounded facts. A failure below may therefore be the Simulated user's doing and not the agent's: for example, `update_matches_goal` fails when the customer accepted a slot outside its targets and the agent booked it correctly. Read the linked conversation before treating a cluster as an agent defect. A reported Run needs the human spot-check, recorded as Spot-check records under `journey_spot_checks/` in the format `agentsim/journey/spot_check.py` defines.

## Outcomes

| pass | fail | task_incomplete | error | not finished |
|---:|---:|---:|---:|---:|
| 4 | 0 | 0 | 0 | 0 |

`fail` and `task_incomplete` are about the agent; `error` means nothing could be concluded.

## Failure clusters (outcome `fail`)

Each cluster groups failures of the same check whose structured details are similar. A cluster is a set of similar failure symptoms, not a proven common root cause.

No failure clusters.

## Task incomplete

Conduct was clean but the Expected outcome was not reached. These Episodes carry no failure record, so they are never in a cluster above; they are grouped by the structured reason evaluation recorded.

No `task_incomplete` Episodes.

## Agent errors

The agent raised while handling a message (a crash, or a model looping past its step limit). The outcome is `error`, but this is the agent's doing, not infrastructure.

No agent errors.

## Infrastructure and harness errors

Transport, timeout, Simulated-user, Judge and evidence problems. They say nothing about the agent.

No infrastructure or harness errors.
