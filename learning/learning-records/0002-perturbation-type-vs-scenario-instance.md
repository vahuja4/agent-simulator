# Perturbation-as-type vs scenario-as-instance distinction addressed

Vishal asked how a predefined perturbation differs from a generated scenario —
surfacing the type/instance confusion: if the curveball catalog is fixed, what
is actually "generated"?

Addressed with real data: the 5-line `card_switch` declaration appears in 168
distinct blueprints (436 for submission_failure, 308 for partial_disclosure,
of 740 total); two blueprints sharing it were contrasted (different policies,
different second curveball, different assertions). Generation contributes the
combination, the concrete instantiation ($6,000, 0767→4421), the consequence
wiring (assertions/criteria), and the prose realization — none of which live
in the catalog.

**Evidence**: pending — watch whether the distinction is used correctly in
follow-ups before treating it as solid.

**Implications**: when teaching the enumerator/sampler internals, lean on the
"catalog = vocabulary, blueprint = sentence" framing; it resolved this
confusion. Related earlier confusion (also type-vs-instance shaped): whether
generation depends on existing scenarios.
