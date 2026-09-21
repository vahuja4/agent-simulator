"""The Journey-driven path: an explicit Journey definition plus Fixture state
in, a normalized Trace retrieved after the conversation, Journey-specific
Assertions and Judge criteria over it.

Parallel to the payments path and free of it: nothing here imports
``fixtures.paycard``, the payments Scenario loader or the mock, so a Scenario
of a new Journey loads and is checked without them. Contract:
``docs/plans/langgraph-harness.md``.
"""
