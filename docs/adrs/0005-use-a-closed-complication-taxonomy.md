# Use a closed Complication taxonomy with reviewed applicability

The Complication axis has exactly nine values: none, underspecification,
mid-conversation correction, goal shift, multi-intent turn, false premise,
out-of-scope drift, channel noise, and ambiguous reference. Every Scenario has
exactly one value. Synthesized Scenarios use at most one non-none value.

Ambiguous reference is distinct from underspecification. It supplies a fact
that matches multiple real fixture entities and tests disambiguation;
underspecification omits a required fact and tests elicitation. False premise
requires an actual incorrect belief about real fixture state. A below-minimum
request made with correct knowledge is therefore none: the warning is a
journey/fixture condition, not conversational difficulty.

Applicability is governed by a reviewed precondition matrix rather than being
universal or split into journey-specific taxonomies. Each value identifies the
journey edges or events and fixture conditions it requires. Goal shift and
multi-intent turn apply only when the approved graph represents both affected
goals or intents without inventing a hidden journey. False premise additionally
requires a real fixture fact about which the premise can be wrong. Missing
semantic support is a pair-eligibility exclusion under the approved
non-applicability code; missing implementation support is BLOCKED.

The matrix follows the pair-exclusion review contract. Coverage reports bind to
both artifacts' versions or hashes. A change that reduces obligations requires
explicit review, and affected entries are re-reviewed when journey graphs,
fixtures, or this taxonomy change.

Procedure branches, validation outcomes, tool failures, and fixture conditions
are not conversational Complications. The first synthesized realization of a
value with no curated example is also a test of that value's definition;
boundary ambiguity must receive an explicit ruling before candidates using the
value can be admitted.
