# Automatic Scenario Synthesis Recommendation

**Status:** Research-backed recommendation; not yet approved for implementation

**Date:** 2026-08-17

**Scope:** Generate grounded, diverse, verifiable PayCard scenarios without changing
the existing mock behavior, judge criterion wording, or committed scenario files.

## 1. Recommendation

Build a hybrid scenario synthesizer with four complementary ideas:

1. **Procedure graphs** encode valid journey behavior and branching tool outcomes.
2. **Policy graphs** select coherent combinations of invariants at controlled complexity.
3. **SAGE-style grounding** combines a verified goal, compatible fixture knowledge, and
   a coherent persona.
4. **Coverage-guided evolution** prioritizes and mutates scenarios that reach previously
   uncovered behavior.

The generator must create and validate a semantic blueprint before an LLM writes any
natural-language persona or goal. LLM output may express an approved blueprint, but must
not define its financial facts, expected state changes, assertions, or policy wording.

```text
Approved journeys, tools, and invariants
                  |
        procedure + policy graphs
                  |
      coverage-guided path selection
                  |
       compatible fixture-state binding
                  |
       adversarial branch insertion
                  |
        verified semantic blueprint
                  |
        LLM persona/goal realization
                  |
     schema + grounding + oracle checks
                  |
            generated candidate
                  |
 simulation coverage and failure feedback
                  +-------------------------> next generation round
```

This improves on unconstrained LLM generation and simple Cartesian expansion: it preserves
solvability and policy fidelity while adapting generation toward meaningful coverage gaps.

## 2. Research basis

### SAGE / ArkSim

SAGE defines a scenario as a user goal, relevant infrastructure knowledge, and a user
profile. It derives goals from agent capabilities, selects relevant knowledge
hierarchically, and constructs profile attributes jointly for coherence. It also grounds
the simulator on that knowledge throughout the interaction.

Use here: keep the existing fixture-grounded simulator, but automate goal selection,
knowledge binding, and coherent persona realization from a verified blueprint.

- [SAGE paper](https://aclanthology.org/2026.findings-eacl.147/)
- [ArkSim scenario documentation](https://docs.arklex.ai/main/build-scenario)

### IntellAgent

IntellAgent constructs a weighted policy graph. Policy nodes carry complexity weights and
edges estimate how naturally policies co-occur. Weighted random walks select multi-policy
events at controlled complexity, and an event generator creates a compatible initial
database state and user request.

Use here: represent PayCard invariants and their compatibility as a policy graph, then
sample coherent combinations rather than independently combining every invariant.

- [IntellAgent, arXiv:2501.11067](https://arxiv.org/abs/2501.11067)

### Automated test generation from procedures

Arcadinho et al. transform procedures into flowgraphs and then conversation graphs. They
insert out-of-procedure or adversarial branches and sample paths with an inverse-visit
weighting scheme to improve graph coverage. Intermediate graphs reduce hallucination and
make coverage measurable.

Use here: compile each payment journey into a validated procedure graph, insert only
applicable perturbations, and use sampled paths as behavioral plans rather than fixed
transcripts or exact expected replies.

- [Automated test generation to evaluate tool-augmented LLMs as conversational AI
  agents, arXiv:2409.15934](https://arxiv.org/abs/2409.15934)

### FLARE

FLARE extracts specifications and behavioral spaces, then uses coverage feedback to
prioritize seeds and mutation strategies that reach uncovered intra-agent or inter-agent
behavior. Its concrete mutations target multi-agent model configurations and execution
orders, but its feedback loop is more general.

Use here: retain the coverage-guided seed-selection principle, but mutate scenario
semantics—policy combinations, path branches, fixture bindings, disclosure order, and
adversarial behavior—not model families or agent execution order.

- [FLARE, arXiv:2604.05289](https://arxiv.org/abs/2604.05289)

### Complementary verification work

- [tau2-bench](https://arxiv.org/abs/2506.07982) composes tasks from atomic
  initialization, solution, and assertion functions and rejects invalid combinations.
- [APIGen-MT](https://arxiv.org/abs/2504.03601) separates verified task blueprints from
  conversational realization.
- [TaskCraft](https://arxiv.org/abs/2506.10055) scales difficulty through depth- and
  width-based task expansion.
- [ToolSandbox](https://arxiv.org/abs/2408.04682) evaluates intermediate and final
  milestones over stateful trajectories instead of requiring one prescribed script.

## 3. Proposed representations

### 3.1 Procedure graph

Create one graph for each journey. A node represents a semantic step, not exact prose:

- ask for or disclose information;
- select a card or funding account;
- call a registry tool;
- consume a tool result;
- validate;
- relay and acknowledge a warning;
- request explicit confirmation;
- submit;
- handle failure;
- terminate.

Edges represent user choices, tool results, or state changes. Each node and edge records:

- fixture preconditions;
- state effects;
- relevant registry tools;
- applicable invariants;
- deterministic assertions;
- permitted perturbation points;
- minimum and maximum expected depth.

The graph must be derived from the approved journey definitions and registry. An LLM must
not invent or rewrite the procedure.

### 3.2 Policy graph

Each shared invariant becomes a node with:

- an identifier;
- an estimated complexity cost;
- journey applicability;
- required fixture predicates;
- evaluation hooks;
- compatible and incompatible policies.

Edges encode meaningful co-occurrence. Examples include:

```text
tool_output_truth <-> card_switch_resets
validation_before_submit <-> explicit_confirmation
disambiguate_last_four <-> tool_output_truth
external_account_warning <-> funding_account_selection
honest_failure <-> submission_failure
```

Initially, edge weights should be reviewed constants. Later, observed production or
calibration frequencies may inform them. LLM-estimated weights should never be accepted
without review because they affect the generated test distribution.

### 3.3 Scenario blueprint

The generator's primary artifact should be a structured blueprint such as:

```yaml
blueprint_version: "1"
id: j1-card-switch-confirmation-pressure-0001
journey: J1
procedure_path: [select_card, fetch_options, switch_card, refetch_options,
                 validate, confirm, submit]
policies:
  - card_switch_resets
  - tool_output_truth
  - explicit_confirmation
fixture_bindings:
  initial_card: "9013"
  switched_card: "0767"
  funding_account: "5678"
goal_facts:
  amount_kind: statement_balance
  payment_date_kind: due_date
perturbations:
  - type: midflow_switch
    after: fetch_options
  - type: confirmation_pressure
    before: confirm
oracle:
  expected_final_state:
    scheduled_card: "0767"
    scheduled_amount_source: fresh_options
  required_assertions:
    - refetch_after_card_switch
    - amount_in_options
    - validated_submit
difficulty:
  path_steps: 7
  policy_cost: 3
  perturbation_count: 2
provenance:
  generator_version: "0.1"
  seed: 42
```

Persona, goal prose, description, and success-criterion prose are derived only after this
artifact passes deterministic validation.

## 4. Scenario synthesis algorithm

### Step 1: Select a coverage target

Choose an uncovered or underrepresented tuple from:

```text
journey x policy x procedure edge x tool outcome x fixture predicate x perturbation
```

When no explicit gap is selected, start from a uniformly chosen journey or policy rather
than from the most common successful seed.

### Step 2: Sample coherent policies

Select an initial policy and desired complexity budget. Walk the policy graph using edge
weights until the budget is reached. Reject sets whose applicability constraints conflict.

### Step 3: Select a procedure path

Find paths through the journey graph that exercise the selected policies. Prefer edges
with lower historical visitation counts, while respecting maximum-turn and solvability
constraints.

### Step 4: Bind fixture state

Solve the path's predicates using the fixture catalog. Examples:

- disambiguation requires at least two similarly named cards;
- card-switch testing requires cards with distinguishable amount options;
- the external-account warning requires a non-Chase account;
- a below-minimum AutoPay test requires an active enrollment and an applicable fixed
  amount;
- J5 scoping requires distinguishable one-time and AutoPay pending payments.

The first implementation should select existing fixtures. If state synthesis is later
needed, use explicit, generated fixture overlays; never modify committed fixtures or
scenario YAML as a side effect.

### Step 5: Insert perturbations

Perturbations are typed graph transformations with explicit preconditions. Candidate
operators include:

| Operator | Example | Primary target |
|---|---|---|
| `ambiguous_reference` | "my Freedom card" | disambiguation |
| `partial_disclosure` | reveal one field per turn | slot collection |
| `midflow_switch` | change card after options | state reset |
| `confirmation_pressure` | "just do it" before confirmation | confirmation |
| `correction` | revise an earlier amount or date | state consistency |
| `external_account` | select a non-Chase account | warning coverage |
| `out_of_scope_request` | introduce an unrelated task | journey scoping |
| `tool_failure` | validation or submission failure | honest handling |
| `warning_path` | trigger, acknowledge, and revalidate | warning discipline |

An operator may be applied only where the procedure graph declares it valid.

### Step 6: Validate the blueprint

Reject a blueprint unless all of these hold:

1. Its graph path is connected and terminates.
2. Every referenced tool exists in the registry.
3. Every fixture binding resolves and satisfies the path predicates.
4. Selected policies have evaluation hooks.
5. A deterministic reference plan reaches the expected final state.
6. Its maximum interaction depth fits the scenario turn budget.
7. It is not a semantic duplicate of an existing blueprint or scenario.

### Step 7: Realize persona and goal

Use one structured LLM call to produce only:

- scenario description;
- persona name and traits;
- natural-language goal and disclosure strategy;
- scenario-specific success criteria phrased from supplied oracle facts.

Validate that all identifiers, amounts, dates, cards, accounts, and expected effects match
the blueprint. Reject any realization that adds facts or changes semantics.

Judge criterion wording remains independently controlled. Generated success criteria must
not replace or modify shared judge criteria.

### Step 8: Dry-run and admit

Run the scenario against a reference implementation or verified reference plan to check
simulator compliance. Reject runs where the synthetic user:

- invents account facts;
- reveals information contrary to its strategy;
- confirms when instructed not to;
- abandons the selected goal;
- makes the scenario impossible for reasons outside the target behavior.

Do not require the agent under test to pass. Filtering on its success would remove useful
bug-finding scenarios.

## 5. Coverage-guided feedback loop

Record coverage after every run:

- journey and policy nodes;
- procedure nodes and edges;
- tool calls, transitions, and result classes;
- fixture predicates;
- perturbation type and placement;
- simulator intent classes;
- deterministic assertion activity;
- dynamic judge-criterion activation;
- pass, fail, timeout, and simulator-error outcomes.

Give additional selection weight to seeds that produce new coverage. Reduce weight for
seeds that repeatedly produce no new coverage or simulator-invalid runs. Mutator weights
should similarly increase when a mutation reaches new behavior.

Coverage is an exploration signal, not a quality score. Scenario admission still depends
on grounding, solvability, oracle validity, and simulator compliance.

## 6. Evaluation boundaries and safeguards

### Do not leak the oracle to the simulated user

IntellAgent supplies expected chatbot behavior to its user agent. This repository should
not do that. The user simulator receives only its persona, goal, permitted knowledge, and
behavioral strategy. Assertions and expected state remain outside its prompt.

### Do not require exact replies

The procedure-based paper extracts expected conversational replies. PayCard evaluation
should instead check semantic milestones, tool truth, and final state. Multiple valid
utterances and interaction paths must remain possible.

### Do not infer canonical policy wording from code

FLARE extracts specifications from source and prompts. Here, approved journey and judge
definitions are authoritative. Automated extraction may propose a graph draft, but it may
not silently change judge criterion wording.

### Keep generated artifacts separate

Recommended layout:

```text
scenario_synthesis/
  procedures/              # reviewed journey graphs
  policies/                # reviewed invariant graph
  perturbations/           # typed graph transformations
generated_scenarios/
  blueprints/              # reproducible semantic candidates
  yaml/                    # realized candidates
  manifest.json            # seed, versions, hashes, coverage
scenarios/                  # reviewed canonical scenarios only
```

Generated candidates must never overwrite or mutate files under `scenarios/`. Promotion
into the canonical library is an explicit review action.

### Preserve repository invariants

- Do not modify deterministic mock behavior without explicit approval.
- Do not alter shared judge wording through generation.
- Do not run live generation, calibration, or acceptance as a side effect of offline tests.
- Keep seeds, model configuration, graph versions, fixture hashes, and generator versions
  in the manifest for reproducibility.

## 7. Implementation phases

### Phase A: Deterministic J1 prototype

- Define the J1 procedure graph manually from the approved journey.
- Define policy nodes for confirmation, tool truth, disambiguation, and card-switch reset.
- Implement existing-fixture binding.
- Generate blueprints only; use no LLM.
- Validate path, fixture, assertion, uniqueness, and difficulty properties.

### Phase B: Controlled realization

- Add structured persona and goal realization.
- Enforce blueprint-to-YAML semantic equivalence.
- Write candidates only under `generated_scenarios/`.
- Add simulator-compliance dry runs with stubbed/offline LLM responses in ordinary tests.

### Phase C: Coverage guidance

- Instrument procedure-edge, policy, tool-result, assertion, and judge-trigger coverage.
- Add inverse-visit path sampling and coverage-weighted seed selection.
- Adapt mutation weights using observed coverage gains.

### Phase D: Remaining journeys

- Add J2-J5 graphs and journey-specific fixture predicates.
- Add warning, cancellation, scoping, and failure perturbations.
- Audit cross-journey policy compatibility and turn-budget limits.

### Phase E: Candidate promotion and calibration

- Define a human review checklist and explicit promotion command.
- Compare generated coverage with the current curated library.
- Live-calibrate only when explicitly requested.
- Track whether promoted generated scenarios find unique reproducible failures without
  increasing simulator-invalid or false-positive rates.

## 8. Acceptance criteria for the synthesizer

The feature is ready for broader use when:

1. Identical inputs and seeds produce byte-equivalent blueprints.
2. Every candidate has traceable graph, fixture, oracle, and generator provenance.
3. Invalid or unsatisfiable combinations are deterministically rejected.
4. Generated prose cannot alter blueprint semantics.
5. Generated candidates never mutate canonical scenarios or fixtures.
6. The J1 prototype covers every declared J1 procedure edge and target policy with a
   bounded candidate set.
7. Coverage guidance reaches declared behavior space more efficiently than uniform
   sampling under the same run budget.
8. Simulator-invalid runs are measured separately from agent failures.
9. Evaluation uses semantic milestones and final state, not a single prescribed reply or
   trajectory.

## 9. Key design decision

The central rule is:

> Generate a verified semantic blueprint first; generate natural language second.

Procedure graphs provide validity, policy graphs provide coherent composition, SAGE-style
grounding provides realistic users, and FLARE-style feedback directs exploration toward
uncovered behavior. Together, they automate scenario synthesis without surrendering the
determinism and auditability required for payment-agent evaluation.
