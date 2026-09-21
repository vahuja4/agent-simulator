# CONTEXT.md — Shared Vocabulary

This file defines the project's domain language. Agents and humans use
these terms exactly as defined here — in code identifiers, file names,
docs, and conversation. If a decision changes a definition, update this
file in the same commit.

## Vocabulary

- **Scenario** — a declarative test situation: persona + goal + knowledge
  level + zero or one complication + max turns + judge criteria. Stored as a
  file; the unit of test authorship.
- **Curated Scenario** — a hand-authored, reviewed Scenario stored under
  `scenarios/` with no synthesis provenance. The curated library is exactly
  that reviewed set; it is the calibration and compliance-gate denominator.
  A Scenario carrying synthesis provenance is never curated, whatever
  directory it sits in, and the curated loader fails closed on it.
- **Synthesized Journey Scenario** — a Scenario generated from a Journey
  definition and Fixture state on the Journey-definition path. Code owns its
  structure, Fixture bindings, Expected outcome and checks; a model writes only
  narrative fields, and a response that supplies anything else is rejected
  rather than overridden. It is validated — well-formed, grounded in Fixture
  state, Sealed-world — and says `qualification: none`: it is never a
  Candidate and has no Qualification or Admission, and validation claims
  nothing about test quality or coverage. Stored under
  `synthesized_journey_scenarios/`, never under `scenarios/` or the Phase 4.5
  `synthesized_scenarios/`.
- **Journey** — an approved domain workflow through which the simulated user
  pursues a goal. A journey may contain multiple valid paths.
- **Journey definition** — the explicit, reviewed statement of one Journey:
  what the agent is permitted to do, the rules it is required to follow, the
  valid outcomes, which Assertions apply, and the Judge criteria themselves,
  stated in full. Its rules
  constrain only the order of observable events, so every path that satisfies
  them is valid and nothing depends on how the agent is built. Together with
  Fixture state it is the authoritative input for a Journey outside payments.
- **Expected outcome** — the valid outcome a Scenario's Goal should end in
  under its Fixture conditions, derived from the Journey definition rather
  than authored. On the Journey-definition path, whether an Episode reached
  it is decided deterministically from the Normalized Trace, not by a Judge
  criterion.
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
  conversation succeeds or fails relative to the Goal, not to any
  particular phrasing. Within J1, each complete payment instruction (card,
  amount, funding account, and date as specified so far) is a distinct Goal.
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
  changes one or more supplied parameters while preserving the underlying
  Goal. Goal shift explicitly abandons the in-progress Goal and replaces it;
  the number of changed parameters never distinguishes these two values. A
  multi-intent turn contains two independently actionable intents; within J1,
  these are two independently actionable payment instructions. False premise is an actual incorrect
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
  failed production attempts, rejected Candidates, and explicit harness-fault
  Admission invalidations, with side, repetition, check, configuration,
  contract, and evidence attribution.
- **Admission invalidation** — an explicit append-only `harness-fault`
  lifecycle transition that retires an Admission whose evidence was invalidated
  by the harness. It archives the admitted library Scenario, returns the
  Coverage cell to UNCOVERED, and does not consume the cell's K regeneration
  budget. It never relabels or deletes the historical Candidate, Qualification,
  or Admission evidence.
- **Candidate rejection invalidation** — an explicit append-only `harness-fault`
  lifecycle transition that supersedes a Candidate rejection for accounting
  without relabeling or deleting its historical evidence. The invalidated
  rejection does not consume the cell's K regeneration budget.
- **Validation-error invalidation** — an explicit append-only `harness-fault`
  lifecycle transition that supersedes a spurious finalization rejection while
  preserving the valid Qualification and any resulting Admission.
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
  judge pass. On the conversation lifecycle it is one line per message,
  written as the message arrives — a user message before it is sent, so a
  failed send survives there — and carries no tool calls: those are in the
  Trace, and the termination reason and timing are in the Episode record
  beside it.
- **Simulated user** — the LLM role-playing the persona toward the goal.
  Also: synthetic user.
- **Agent adapter** — the interface to the agent-under-test, holding
  whatever session state the backend needs; the only code that knows the
  platform's transport. Two shapes. The payments path's is one method:
  message in → reply + tool calls out. The conversation lifecycle is four
  operations — start an isolated conversation on a given Fixture state, send
  a message (reply text only), retrieve the completed Trace, release — for a
  platform whose tool evidence arrives only after the conversation ends. Its
  errors say whose fault they are: the agent raised, or the infrastructure
  failed. Retrieving a Trace never raises for a platform-side problem; it
  returns the gap. Implementations: `MockAgent` (harness development), the
  journey service adapter (the LangGraph agent standing in), `SierraAgent`
  (headless API + trace fetch).
- **Trace** — the agent platform's record of what the agent did
  internally (tool calls, parameters, results). On the payments path the
  adapter fetches it per Turn and attaches it to turns so judges can see
  actions, not just words. On the conversation lifecycle it is retrieved once,
  after the conversation: the platform's payload is kept untouched as the raw
  Trace, and the adapter copies it into the Normalized Trace.
- **Normalized Trace** — the harness's platform-independent record of one
  completed conversation: messages and agent actions under stable ids in one
  explicit order, each action tied to the user message it handled and the
  reply it produced, with a statement per evidence class (messages, actions)
  of whether it is available, partial, or unavailable. Missing facts are
  stated, never inferred. An Assertion that lacks the evidence it needs is
  unavailable, which is never a pass, and the Judge is shown a Trace only
  when both classes are available.
- **Termination** — the decision that an episode is over, and by whom.
  Termination reason is always recorded. On the payments path: simulated user
  (goal reached / gives up), judge (halt on met/failed criterion), or harness
  (max turns). On the conversation lifecycle the Judge never terminates —
  nothing is judged or asserted until the conversation is over — so it is the
  Simulated user (goal achieved / gave up), the harness (Turn limit, or the
  Episode time limit checked between Turns), or an error (Agent adapter or
  Simulated user). The agent has no end signal: its claiming completion ends
  nothing and establishes nothing. However the conversation ended, the Trace
  is retrieved and the conversation released afterwards, in that order.
- **Judge** — an LLM evaluator from our existing judge infrastructure,
  applied to a transcript (or mid-episode via the judge hook). Judges are
  fail-closed: anything other than an explicit pass is a fail.
- **Judge criterion** — a single named check a judge applies, defined per
  scenario or globally, or — outside payments — stated by the Journey
  definition. Example: goal completion, groundedness,
  say/do consistency.
- **Say/do consistency** — the check that what the agent *claimed* in
  text matches what the trace shows it *did*.
- **Verdict** — the final outcome for an episode, produced by the
  two-layer design: deterministic assertions act as a hard gate over LLM
  judge rulings. An episode passes only if both layers pass. On the
  Journey-definition path the Verdict is assigned once, after the
  conversation, to a saved Episode, and the Expected-outcome gate joins the
  two layers: `pass` needs every Assertion passed, a Judge pass and the
  Expected outcome evidenced in the Normalized Trace. Clean conduct without
  that evidence is `task_incomplete`; an Episode error or unavailable
  evidence is `error`, never `fail` and never `pass`. The Judge is not called
  after an Assertion failure, so it cannot override one.
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
