# Refactoring AgentSim into a Generic Agent-Testing Framework

## Objective

Refactor AgentSim so its core can test any conversational or tool-using agent from a supplied set of journeys, policies, scenarios, and domain knowledge.

PayCard should remain the first reference implementation and calibration suite, but it must become a plugin rather than a dependency of the framework.

The critical completion test is:

> A new domain plugin can be installed and run without editing any file inside `agentsim/`.

## Current position

The repository already has a reusable foundation:

- An asynchronous agent adapter interface
- A turn orchestrator
- Versioned, serializable traces
- A grounded LLM user simulator
- A fail-closed LLM judge
- Deterministic assertions
- YAML scenarios
- A scripting and replay DSL

The principal problem is architectural placement. The core currently contains several PayCard concepts:

- PayCard and Sierra tool names
- Closed `J1`–`J5` journey validation
- Card selection state
- Payment-specific assertion logic
- AutoPay and payment judge criteria
- PayCard fixtures and knowledge rendering
- Default construction of the PayCard mock

## Target architecture

```text
agentsim/                         # Generic framework
  adapters/
    base.py                       # AgentAdapter protocol
  policies/
    types.py                      # Policy, Rule, Trigger, Violation
    engine.py                     # Generic policy execution
    builtin_rules.py              # Reusable deterministic rules
    registry.py                   # Rule type registration
  plugin.py                       # Plugin contract and discovery
  runner.py                       # Runtime composition
  scenario.py                     # Generic scenario schema
  simulator.py                    # Domain-neutral simulated user
  judge.py                        # Generic fail-closed judge
  orchestrator.py                 # Turn loop
  trace.py                        # Versioned trace schema
  script.py                       # Scripted and autonomous turns

agentsim_paycard/                 # First domain plugin
  plugin.py
  adapters/
    mock_paycard/
    sierra_http.py                # Future real-agent adapter
  policies/
    definitions.yaml
    custom_rules.py
    criteria.py
  fixtures/
  scenarios/
  tool_catalog.yaml
  knowledge.py
  calibration/
```

The dependency direction must be one-way:

```text
agentsim_paycard  ─────▶  agentsim
agentsim          ✕─────▶  agentsim_paycard
```

## Design principles

1. Preserve existing PayCard behavior before moving code.
2. Keep execution mechanics in the core and domain semantics in plugins.
3. Use a small, safe declarative rule vocabulary.
4. Permit typed plugin-defined Python rules for complex domain behavior.
5. Keep deterministic checks separate from semantic LLM evaluation.
6. Version traces, scenarios, policies, and plugin manifests.
7. Treat missing adapter evidence as degraded evaluation, not a crash.
8. Prove generality with a second, non-payment plugin.

---

## Phase 0 — Stabilize the current baseline

Before refactoring, preserve a reproducible snapshot of the working Phase 3 implementation.

### Changes

- Commit or otherwise snapshot the current Phase 3 implementation separately from the genericization work.
- Record the offline test baseline.
- Record the expected live calibration results:
  - All 13 defects-off PayCard scenarios pass.
  - D1–D7 are detected by their expected assertion or judge criterion.
- Add characterization tests for:
  - Tool-call sequences
  - Trace serialization
  - Assertion outcomes
  - Criterion activation
  - Scenario validation
  - Script replay

### Acceptance checks

- The current PayCard suite can be executed independently of the refactoring branch.
- Later phases can compare their traces and outcomes with this baseline.
- Phase 3 cleanup is not mixed with package extraction changes.

---

## Phase 1 — Introduce plugin and runtime contracts

Add a plugin layer before moving domain code. Temporary compatibility imports can preserve existing callers during migration.

### Plugin contract

```python
class AgentSimPlugin(Protocol):
    name: str
    version: str

    def validate_scenario(self, scenario: Scenario) -> None: ...
    def render_knowledge(self, knowledge: Mapping[str, Any]) -> str: ...
    def build_policies(self, scenario: Scenario) -> Sequence[Policy]: ...
    def build_criteria(self, scenario: Scenario) -> Sequence[Criterion]: ...
    def create_agent(
        self,
        target: str,
        config: Mapping[str, Any],
    ) -> AgentAdapter: ...
```

The plugin object may bundle smaller providers, but core modules should depend on narrow protocols such as:

- `ScenarioValidator`
- `KnowledgeRenderer`
- `PolicyProvider`
- `CriterionProvider`
- `AgentFactory`

### Plugin discovery

Use Python entry points:

```toml
[project.entry-points."agentsim.plugins"]
paycard = "agentsim_paycard.plugin:plugin"
```

### Required changes

- Add `agentsim/plugin.py`.
- Add plugin discovery and version compatibility checks.
- Add clear errors for missing or incompatible plugins.
- Add `agentsim/runner.py` and a `RuntimeBundle` that contains:
  - Agent adapter
  - Simulator
  - Policy evaluator
  - Judge
  - Scenario
- Remove default construction of `MockPayCardAgent` from the core runner.
- Add temporary deprecated re-exports for old imports.

### Acceptance checks

- A plugin can be loaded and inspected by name.
- Unknown plugins return an actionable error.
- No core module imports a plugin implementation directly.

---

## Phase 2 — Generalize adapter responses and traces

The current `selected_card` field is payment-specific and must leave the core data model.

### New response model

```python
@dataclass
class AgentResponse:
    content: str
    tool_calls: list[ToolCall]
    observations: dict[str, JsonValue] = field(default_factory=dict)
```

PayCard can report namespaced observations:

```python
observations = {
    "paycard.selected_card": "card-freedom-0767",
    "paycard.journey": "one_time_payment",
}
```

### Required changes

- Replace `AgentResponse.selected_card` with `observations`.
- Replace `TraceTurn.selected_card` with observations on agent turns.
- Add generic trace helpers:
  - `latest_observation(key)`
  - `observation_at(key, turn)`
  - `observation_change_turns(key)`
  - `iter_events(selector)`
- Stop copying adapter state onto user turns.
- Bump the trace schema from `1.0` to `2.0`.
- Add deterministic v1-to-v2 migration.
- Convert legacy `selected_card` into `paycard.selected_card` during migration.
- Retain structured degraded checks when observations or results are unavailable.

### Acceptance checks

- Old traces remain readable.
- Schema 2.0 traces round-trip exactly.
- The core trace schema contains no card or payment fields.
- PayCard card-switch checks still work through observation changes.

---

## Phase 3 — Generalize scenarios and user simulation

Split generic scenario validation from plugin-owned domain validation.

### Generic scenario example

```yaml
schema_version: "1.0"
name: ambiguous-resource-selection
plugin: paycard
journey: make_one_time_payment

persona:
  name: Tasha
  traits: casual and cooperative

goal: >
  Pay the statement balance on the intended card.

knowledge:
  cards: ["0767", "4421"]
  accounts: ["5678"]

policies:
  include:
    - paycard.explicit_confirmation
    - paycard.card_disambiguation

success_criteria:
  - The correct card was selected before submission.

max_turns: 14
```

### Core validation should cover

- Schema version
- Scenario name
- Plugin name
- Persona
- Goal
- Arbitrary knowledge mapping
- Success criteria
- Policy references
- Tags
- Turn limits

### Plugin validation should cover

- Valid journey names
- Fixture references
- Domain-specific knowledge shape
- Domain extensions
- Tool names
- Scenario-specific constraints

### Simulator changes

Replace the Chase-specific constructor with injected configuration:

```python
UserSimulator(
    role_description="You are a customer seeking support...",
    persona=persona,
    goal=goal,
    rendered_knowledge=knowledge_text,
    conversation_style=style,
    stop_rule=stop_rule,
)
```

Move PayCard knowledge rendering and customer wording into `agentsim_paycard/knowledge.py`.

### Acceptance checks

- The core loader accepts arbitrary journey names.
- The core loader accepts arbitrary knowledge fields.
- All PayCard scenarios load through PayCard validation.
- The core simulator contains no Chase, card, payment, account, or AutoPay wording.

---

## Phase 4 — Replace payment assertions with a generic policy engine

Split the current assertion module into generic execution and plugin-owned policy definitions.

### Core policy model

```python
@dataclass
class Policy:
    id: str
    description: str
    severity: Severity
    activation: Trigger
    deterministic_rules: list[Rule]
    judge_criterion: Criterion | None = None
```

```python
@dataclass
class PolicyViolation:
    policy_id: str
    rule_id: str
    severity: Severity
    turn_index: int | None
    message: str
    evidence: dict[str, Any]
```

### Initial generic rule types

- `forbid_tool`
- `require_tool_before`
- `require_successful_tool_before`
- `require_user_turn_between`
- `require_argument_match`
- `require_value_from_prior_result`
- `require_tool_after_observation_change`
- `require_result_predicate`

### Example PayCard policy

```yaml
schema_version: "1.0"
id: paycard.validated_one_time_submit
description: A one-time payment must be validated before submission.
severity: critical

rules:
  - type: require_successful_tool_before
    submit_tool: AddOneTimePayment
    required_tool: AddValidateOneTimePayment
    identity:
      submit: /arguments/formId
      required: /result/formId

  - type: require_user_turn_between
    before: AddValidateOneTimePayment
    after: AddOneTimePayment
```

Use JSON Pointer or another restricted path language. Do not permit `eval`, executable YAML, or arbitrary expressions.

When a policy cannot be safely represented by built-in rules, a plugin may register a typed Python `Rule` implementation.

### Acceptance checks

- The core policy engine contains no PayCard tool names.
- D1 and D2 remain deterministically detectable.
- Missing results or observations produce structured degraded evaluations.
- Policy violations have stable IDs, severity, source, turn, and evidence.

---

## Phase 5 — Make the LLM judge domain-neutral

Keep the generic judge mechanics but move payment rulings into the PayCard plugin.

### Keep in the core

- `Criterion` and verdict types
- Generic task-goal completion wording
- Criterion batching
- Dynamic criterion activation hooks
- Structured-output schema generation
- Fail-closed enforcement

### Move to PayCard

- Explicit payment confirmation
- The strict pressure-versus-confirmation policy ruling
- Payment tool-output truth
- Honest payment submission failure
- AutoPay warning acknowledgement
- Card disambiguation
- Card-switch reset
- External-account caveat
- Eastern Time and Saturday disclaimers
- Minimum-due reminders
- Payment journey scoping
- PayCard widget behavior

Complex triggers can initially remain plugin-supplied Python callables. A trigger should become a generic declarative primitive only after multiple domains require the same behavior.

### Acceptance checks

- The core judge prompt contains no payment vocabulary.
- PayCard activates the same criteria on equivalent traces.
- D3–D7 remain caught by their intended PayCard criteria.

---

## Phase 6 — Extract the PayCard plugin

### File migration map

| Current location | Action | Target state |
|---|---|---|
| `agentsim/registry.py` | Move | `agentsim_paycard/tool_catalog.py` |
| `agentsim/criteria.py` | Move | `agentsim_paycard/policies/criteria.py` |
| `agentsim/assertions.py` | Split | Core policy engine plus PayCard rules |
| `agentsim/scenario.py` | Split | Core schema plus PayCard validation |
| `agentsim/simulator.py` | Generalize | Inject role and rendered knowledge |
| `agentsim/adapters/mock_paycard/` | Move | `agentsim_paycard/adapters/mock_paycard/` |
| `fixtures/` | Move | `agentsim_paycard/fixtures/` |
| `scenarios/` | Move | `agentsim_paycard/scenarios/` |
| `agentsim/types.py` | Change | `selected_card` to observations |
| `agentsim/trace.py` | Change | Schema 2.0 observations |
| `agentsim/adapters/__init__.py` | Change | Export generic adapter contracts only |
| `scripts/run_calibration.py` | Move | PayCard calibration tooling |

### Additional changes

- Register `mock` and future `sierra-http` targets through the PayCard plugin.
- Move the Eastern Time constant into PayCard.
- Keep generic `Clock` and `FrozenClock` protocols in the core.
- Move defect flags and calibration artifacts into the plugin.
- Remove compatibility re-exports after all callers are migrated.

### Acceptance checks

- `agentsim` imports and runs without PayCard installed.
- The core never imports `fixtures` or `agentsim_paycard`.
- All 13 PayCard scenarios preserve expected behavior.
- D1–D7 remain visible with the expected failure source.

---

## Phase 7 — Prove generality with a second plugin

Create a small non-payment reference plugin, such as a customer-support or refund agent.

```text
agentsim_support_example/
  plugin.py
  mock_agent.py
  tool_catalog.yaml
  policies.yaml
  knowledge.py
  scenarios/
```

Suggested policies:

- Verify identity before disclosing account information.
- Enforce refund limits returned by tools.
- Require confirmation before cancellation.
- Report failed refund or cancellation tools honestly.

The example should exercise:

- Generic built-in deterministic rules
- A plugin-defined semantic criterion
- Arbitrary domain knowledge
- A planted non-payment defect

### Acceptance checks

- The plugin installs and runs without editing `agentsim/`.
- A planted defect is caught through the standard failure model.
- Both PayCard and the support plugin pass the same plugin contract suite.

---

## Phase 8 — Enforce the architecture automatically

### Test structure

```text
tests/
  core/
  architecture/
  contract/
  plugins/
    paycard/
    support_example/
```

### Architecture checks

- AST-based import test: `agentsim` must not import:
  - `agentsim_paycard`
  - `fixtures`
  - Plugin implementation modules
- Core runtime modules must not contain:
  - PayCard tool constants
  - Closed `J1`–`J5` journey lists
  - Card or AutoPay state fields
- Core tests must run without PayCard on `PYTHONPATH`.
- Plugin discovery must work through entry points.
- Every plugin must pass a shared contract suite.
- Trace and scenario schema migrations must be tested.

### Acceptance checks

- Introducing a domain import into the core causes CI to fail.
- Core, plugin, and live tests can run as separate CI jobs.
- Both reference plugins pass the shared contract suite.

---

## Phase 9 — Add generic CLI, batching, and reporting

Implement reporting only after the plugin boundary is enforced, so the report model does not inherit PayCard fields.

### Generic CLI

```bash
agentsim run \
  --plugin paycard \
  --suite agentsim_paycard/scenarios \
  --target mock \
  --runs 5
```

```bash
agentsim run \
  --plugin support-example \
  --suite support_scenarios \
  --target mock
```

### Generic report fields

- Plugin and plugin version
- Scenario and journey/workflow label
- Run and target adapter
- Policy or criterion ID
- Failure source
- Severity
- Turn index
- Structured evidence
- Degraded checks
- Trace schema version
- Reproduction script
- Cluster label and affected scenarios

### Acceptance checks

- The same CLI and reporter handle both reference plugins.
- No report template contains card, payment, or AutoPay-specific fields.
- CI gates can operate by generic severity or policy ID.

---

## Testing strategy

### Core unit tests

- Plugin discovery
- Trace creation and migration
- Generic scenario loading
- Policy evaluation
- Judge fail-closed behavior
- Scripts and replay
- Orchestration and outcome derivation

### Plugin contract tests

- Plugin metadata
- Scenario validation
- Knowledge rendering
- Policy construction
- Criterion construction
- Target creation
- Error behavior

### PayCard regression tests

- All mock journey tests
- All scenario tests
- All assertion tests
- All criterion activation tests
- All calibration regressions
- D1–D7 defect detection

### Second-plugin tests

- Non-payment scenario execution
- Generic rule reuse
- Plugin-specific rule registration
- Planted defect detection

### Architecture tests

- Dependency direction
- Forbidden imports
- Core-only installation
- Entry-point loading
- Schema isolation

### Live tests

- Remain plugin-specific
- Stay excluded from the default offline suite
- Record model and plugin versions in artifacts

---

## Compatibility strategy

1. Add new contracts before moving existing modules.
2. Preserve old imports temporarily with deprecation warnings.
3. Migrate traces explicitly instead of supporting two schemas indefinitely.
4. Update scenario files mechanically, then review their semantics manually.
5. Compare PayCard tool sequences and outcomes after every extraction phase.
6. Remove compatibility paths only after internal callers and calibration tools use the plugin API.

---

## Recommended implementation order

1. Snapshot Phase 3 and add characterization tests.
2. Add plugin discovery and `RuntimeBundle` composition.
3. Replace `selected_card` with namespaced observations.
4. Add trace schema 1.0-to-2.0 migration.
5. Split generic scenario validation from plugin validation.
6. Make the simulator role and knowledge injectable.
7. Introduce the generic policy engine.
8. Port deterministic PayCard checks onto generic rules.
9. Move PayCard judge criteria and triggers into the plugin.
10. Move the mock, fixtures, tool catalog, scenarios, and calibration tooling.
11. Add a second domain plugin.
12. Add architecture enforcement to CI.
13. Build the generic CLI, batching, clustering, HTML report, and CI gate.
14. Implement Sierra HTTP as a PayCard target rather than core functionality.

---

## Definition of done

- A new domain can be installed through an entry point without modifying `agentsim/`.
- The core contains no PayCard tools, card state, payment assertions, AutoPay rules, fixtures, or closed journey enumeration.
- Core scenarios accept arbitrary journey and knowledge values.
- Plugins own domain validation, knowledge rendering, policies, criteria, targets, fixtures, and scenarios.
- Policies support generic declarative rules plus typed plugin rules.
- The core judge is domain-neutral and remains fail-closed.
- Trace schema 2.0 records namespaced observations and migrates schema 1.0 traces.
- All 13 PayCard defects-off scenarios pass.
- D1–D7 remain detectable by their expected source.
- A second non-payment plugin catches a planted defect.
- The CLI and reporter work for both plugins.
- Architecture tests prevent domain dependencies from returning to the core.

The final proof is the ability to install a previously unknown plugin, run its scenarios, evaluate its deterministic and semantic policies, serialize its traces, and generate its report without changing or rebuilding the AgentSim core.
