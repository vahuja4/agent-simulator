# Break the agent — plan review

Reviewed 2026-09-25 on `codex/langgraph-synthesis-harness`. Recommendations
only; no design decision adopted, implementation changed, or live call made.
Source: `docs/plans/break-the-agent.md`, checked against `CONTEXT.md`, the
Journey-definition lifecycle, evaluation, Assertions, Spot-check records,
the four `live-dev-01` Synthesized Journey Scenarios, and the recorded
Simulated-user fidelity decision. The reliability report was read as local
background; its external research claims were not independently verified.

Separating `probe` discovery from `run` measurement, retaining a Cooperative
Persona control, and requiring human confirmation are sound choices. Resolve
the following before implementing the proposed loop.

1. **Detection is after the conversation.** The Agent adapter returns reply
   text during the conversation; the Trace arrives afterwards. Assertions
   and the Judge run in `agentsim/journey/evaluation.py` on saved evidence.
   The plan's suspected-problem limit and `break_found` Termination therefore
   have no defined online source. Prefer post-conversation findings for the
   first version. If a Simulated-user suspicion ends an Episode, distinguish
   that provisional signal from an evaluated finding. The prototype must
   retain the Agent adapter boundary and retrieve/release lifecycle even
   though it bypasses `run_episode`.
2. **The self-check revisits an explicit decision.**
   `docs/solutions/journey-simulated-user-fidelity-is-a-human-record.md`
   rejects self-report fields and deviation flags, not merely their use in
   the Verdict. The rewrite-and-mark proposal may be useful, but calling it
   outside the Verdict does not make it consistent with that decision.
   ADR 0008 should explicitly propose the limited change and state that an
   unmarked message establishes no fidelity evidence.
3. **Attack tactics need Scenario constraints.** The four existing Scenarios
   have different Personas and Complications: vigilant/ambiguous reference,
   persistent/channel noise, cooperative/none, and pressure/mid-conversation
   correction. Applying a blanket stay-ambiguous-and-push tactic would risk
   changing those axes or combining non-none Complications. Define eligible
   tactics per Scenario, retain the Cooperative Persona control, and create
   explicit separate inputs or overlays when a different Scenario is needed.
   Do not silently change the committed Scenarios.
4. **Termination must not predetermine the findings.** `no_progress` alone
   cannot establish clean conduct or task incompletion: a violation or even
   the Expected outcome could precede the repeated replies. Also, evaluation
   currently returns `error` before checking evidence for an Episode error.
   Making `out_of_scope` an error without defining independent probe finding
   extraction could hide an earlier violation. Preserve the existing Verdict
   rules and specify how probe review retains earlier evidence separately.
5. **Measure missed failures, too.** Reviewed-suspicion yield and suspicion
   count cannot distinguish a robust agent from a detector that misses its
   failures. Add known failing and clean saved-evidence cases for the detection
   path, and human review of a sample of Episodes with no suspicion. This does
   not require changing the payments mock or Judge criterion wording. Multiple
   claims about one underlying problem should not inflate discovery yield.

Smaller clarification: `update_matches_goal` checks successful updates against
the Scenario Goal. An agent guessing the intended appointment by chance can
still violate the customer-choice rule without failing that Assertion; the
`appointment_identified` Judge criterion remains necessary. A Cooperative
Persona is a control for interpersonal pressure, not proof the agent must pass.

## Compound record

These are open plan findings, not observed mock defects or Judge ruling
variance; no M-, N-, or D-series entry is warranted. No new domain meaning or
settled design decision requires a vocabulary or solution update. No
implementation failure was reproduced, so no test was added or run. Future
implementation acceptance checks should cover post-conversation detection,
Scenario fidelity constraints, and violations preceding each probe ending.
There were no carried-over findings in this conversation. This record retains
the current findings without treating the recommendations as approved changes.
