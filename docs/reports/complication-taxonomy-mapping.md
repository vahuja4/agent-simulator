# Curated-scenario Complication mapping

Verified against all 13 committed YAML files under `scenarios/` on 2026-08-26.
Every Scenario maps to exactly one value in the reviewed closed taxonomy.

| Scenario | Complication | Boundary ruling |
|---|---|---|
| `j1-ambiguous-freedom-card` | ambiguous reference | "Freedom card" matches two real cards and tests disambiguation, not elicitation. |
| `j1-card-switch-stale-options` | mid-conversation correction | The chosen card changes while the payment Goal remains. |
| `j1-happy-path` | none | Everything-upfront control; the contradictory Persona phrase is tracked separately for correction. |
| `j1-happy-path-minimal-opener` | underspecification | Required facts are deliberately supplied only when asked. |
| `j1-large-payment-false-success` | none | Submission failure is a journey/tool outcome; asking for status belongs to Goal and success criteria. |
| `j1-pressure-skips-confirmation` | none | Pressure is Persona behavior, not a Complication. |
| `j2-external-funding-account` | none | External funding is Fixture state and the missing caveat is a Fitness target. |
| `j2-happy-path` | none | Direct control behavior. |
| `j3-below-minimum-fixed-autopay` | none | The user correctly knows the amount is below minimum; the warning is a journey/fixture condition, not a false premise. |
| `j3-happy-path` | none | Direct control behavior. |
| `j4-happy-path` | none | Direct control behavior. |
| `j5-cancel-autopay-pending` | false premise | The user incorrectly treats a real pending AutoPay payment as cancellable through J5. |
| `j5-happy-path` | none | Direct control behavior. |

## Coverage gap map

The curated distribution is 9 none and 4 non-none: one each of ambiguous
reference, mid-conversation correction, underspecification, and false premise.
Goal shift, multi-intent turn, out-of-scope drift, and channel noise have zero
curated instances. This is the curated library's difficulty gap and the primary
initial synthesis target.

Those four values are **designed, not yet empirically validated**. The first
synthesized Scenario that realizes each value is also a definition test. Any
boundary ambiguity it exposes—for example, whether a card-payment-to-card-payment
change is goal shift or mid-conversation correction—must receive an explicit
boundary ruling before candidates using that value can be admitted.

The 9 none / 4 complicated distribution is required input to the later
near-duplicate and library-budget decision.
