# Curated-scenario Persona archetype mapping

Verified against the 13 committed YAML files under `scenarios/` on 2026-08-26. The mapping classifies behavior actually required by each Persona and Goal; it does not infer identity from temperament adjectives.

| Scenario | Archetype | Complication decomposition | Verification note |
|---|---|---|---|
| `j1-ambiguous-freedom-card` | Cooperative | Underspecification | Withholding the last four until asked is the Complication; casual nickname use is surface style. |
| `j1-card-switch-stale-options` | Vigilant | Mid-conversation correction | Changing cards is the Complication. Challenging stale dollar figures supplies the distinct Vigilant behavior. |
| `j1-happy-path` | Cooperative | None | The description and Goal specify an everything-upfront control path. See the mismatch below. |
| `j1-happy-path-minimal-opener` | Cooperative | Underspecification | The Goal explicitly requires an underspecified opener and one-at-a-time disclosure. Terseness is not identity. |
| `j1-large-payment-false-success` | Cooperative | None | Asking whether the payment succeeded is explicitly in the Goal and success criteria, not a separate archetype. The failed-submission path is journey behavior, not a conversational Complication. |
| `j1-pressure-skips-confirmation` | Pressure | None | The user rushes an in-scope payment past confirmation; the eventual confirmation behavior is governed by the Luna decision. |
| `j2-external-funding-account` | Cooperative | None | External funding is Fixture state and the warning is a Fitness target. The Goal does not require the user to challenge a missing caveat, so “expects to be told” does not establish Vigilant behavior. |
| `j2-happy-path` | Cooperative | None | Direct control behavior. |
| `j3-below-minimum-fixed-autopay` | Cooperative | None | The below-minimum choice creates a warning path; acknowledging a correct warning is part of the Goal, not Persona identity. |
| `j3-happy-path` | Cooperative | None | Briefness and decisiveness are surface traits on a direct control path. |
| `j4-happy-path` | Cooperative | None | Calmness and concision are surface traits on a direct control path. |
| `j5-cancel-autopay-pending` | Persistent | False premise | The user re-attempts after the correct scope refusal, which is attrition against refusal. Treating the pending AutoPay item as cancellable supplies the single Complication. |
| `j5-happy-path` | Cooperative | None | Matter-of-fact brevity is surface style on a direct control path. |

## Findings

1. `j1-happy-path` has a real decomposition mismatch: its file comment, description, and Goal specify an everything-upfront opener, while its Persona says “answers one question at a time.” That phrase belongs to underspecification when behaviorally enforced and otherwise is surface style. The curated YAML needs a later, explicitly authorized correction; this report does not mutate it.
2. No curated Scenario declares Knowledge level because the current YAML schema has no such field. None explicitly requires confused-customer behavior or wrong-term usage, so assigning low, medium, or high retroactively would be invention rather than verification.
3. No curated persona falls outside the four-archetype set after Persona, Goal, Complication, Fixture state, and Fitness target are separated as above.
