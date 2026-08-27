# CONTEXT.md — Shared Vocabulary

This file defines the project's domain language. Agents and humans use
these terms exactly as defined here — in code identifiers, file names,
docs, and conversation. If a decision changes a definition, update this
file in the same commit.

## Vocabulary

- **Scenario** — a declarative test situation: persona + goal + knowledge
  level + zero or one complication + max turns + judge criteria. Stored as a
  file; the unit of test authorship.
- **Journey** — an approved domain workflow through which the simulated user
  pursues a goal. A journey may contain multiple valid paths.
- **Persona** — who the simulated user is: background, temperament,
  communication style. Grounded top-down (from the scenario spec) and
  bottom-up (from what such a user would plausibly know). A pressure Persona
  follows the confirmation-gate behavior recorded in
  `docs/solutions/simulator-model-luna.md`.
- **Persona archetype** — a reviewed behavioral category of Persona admitted
  only when it can plausibly make the agent fail differently from existing
  archetypes. Temperament synonyms are not distinct archetypes.
- **Cooperative Persona** — supplies requested information and accepts clear,
  satisfactory guidance. It is the control archetype for detecting agent and
  harness false alarms without adversarial interpersonal pressure.
- **Pressure Persona** — rushes past a gate for an in-scope action the agent is
  willing to perform, probing confirmation-skip failures. Its confirmation-gate
  behavior is defined in `docs/solutions/simulator-model-luna.md`.
- **Vigilant Persona** — challenges inconsistent, surprising, or insufficiently
  explained information, probing truthfulness and clarification failures.
- **Persistent Persona** — re-attempts after a refusal or unsatisfactory answer,
  probing wear-down compliance and degradation into repetition. Pressure is
  speed against procedure; persistence is attrition against refusal.
- **Goal** — what the simulated user is trying to get done. The
  conversation succeeds or fails relative to the goal, not to any
  particular phrasing.
- **Knowledge level** — the simulated user's relevant factual and procedural
  fluency, classified as low, medium, or high. Low exhibits a material fluency
  gap; medium knows Goal-relevant facts but visibly relies on the agent for a
  rule or consequence; high correctly states a relevant rule or consequence
  without prompting. Knowledge level does not control disclosure timing, and
  identical behavior cannot evidence more than one level.
- **Sealed-world rule** — every factual claim available to a simulated user
  must resolve to its Scenario Goal, Fixture state, or represented domain
  rules and consequences. At low Knowledge level, an incorrect label for a
  real fact is allowed, but an invented fact is not. An incorrect belief about
  real Fixture state belongs to the false-premise Complication at every
  Knowledge level, including high.
- **Complication** — a closed Scenario axis with exactly nine values: **none**,
  **underspecification**, **mid-conversation correction**, **goal shift**,
  **multi-intent turn**, **false premise**, **out-of-scope drift**, **channel
  noise**, and **ambiguous reference**. Underspecification withholds required
  facts initially or supplies them only when asked. Mid-conversation correction
  changes one supplied choice or parameter while preserving the underlying
  Goal. Goal shift replaces the Goal; a multi-intent turn contains two
  independently actionable intents. False premise is an actual incorrect
  belief about real Fixture state, never an invented fact. Out-of-scope drift
  is a transient request beyond the Journey while the original Goal remains.
  Channel noise materially obscures meaning and requires recovery; cosmetic
  phrasing is surface variation. An ambiguous reference supplies a fact that
  matches multiple real fixture entities and requires disambiguation rather
  than elicitation. Every Scenario has exactly one value, and synthesized
  Scenarios never combine non-none values. Use **Complication**, not
  *perturbation*, for this axis.
- **Fixture state** — the grounded domain data available at the start of an
  episode. Synthesized scenarios may select only fixture states that actually
  exist; fixture states with equivalent scenario-relevant properties belong to
  the same fixture-state equivalence class.
- **Fitness target** — a known planted-defect class that a synthesized scenario
  is expected to expose as a particular structured failure. Fitness-target
  coverage does not claim coverage of unknown defect classes.
- **Detection-unproven** — provenance status for an admitted synthesized
  Scenario whose Coverage cell has no applicable known Fitness target. It has
  passed defects-off precision but has not demonstrated sensitivity to a
  planted defect.
- **Coverage cell** — one eligible semantic combination of journey path,
  Persona archetype, Knowledge level, Complication, fixture-state equivalence
  class, and Fitness target. Surface realization such as opener wording is not
  part of the cell.
- **Blueprint** — the strict, versioned, deterministic semantic specification
  of one Coverage cell before surface realization. It binds the six axes,
  ordered journey-edge IDs, concrete Fixture facts, required checks, limits,
  and source provenance. Its `cell_id` is Same-cell identity; its
  `blueprint_id` changes for any semantic Blueprint change but not for a
  provenance timestamp change. Pre-Phase-4.5 prototype blueprints are legacy
  reconciliation inputs, not Blueprints eligible for candidacy.
- **Candidate** — one immutable, schema-valid synthesized Scenario realization
  of a Blueprint awaiting Qualification. Candidate ordinal 0 is the initial
  realization; ordinals 1 and 2 are whole-candidate replacements after Fitness
  rejection. Corrective realization attempts happen before candidacy and do
  not consume these ordinals.
- **Qualification** — the immutable evidence bundle and pure admission
  evaluation for one Candidate. It contains the required N repetitions on the
  defects-off side and, when a Fitness target applies, the defect-on side.
- **Rejection ledger** — the append-only, hash-linked JSON Lines history of
  failed production attempts and rejected Candidates, with side, repetition,
  check, configuration, contract, and evidence attribution.
- **Historical quarantine** — the read-only `generated_scenarios/` prototype
  output. It may supply reconciliation facts but never a candidate, admission,
  Fitness result, or coverage denominator.
- **BLOCKED** — an eligible coverage obligation that the current implementation
  or generator cannot realize for a recorded reason. It is engineering debt,
  not an eligibility exclusion, and is expected to trend to zero.
- **UNCOVERED** — an eligible, realizable coverage obligation for which no
  Scenario has yet been admitted, whether it has not been attempted or its
  attempted candidates were rejected. It is pipeline backlog and is never
  pooled with BLOCKED obligations.
- **Same-cell equivalence** — two scenarios are same-cell equivalent when every
  Coverage cell axis is equal, regardless of differences in surface realization.
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
