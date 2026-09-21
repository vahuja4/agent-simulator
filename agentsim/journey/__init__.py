"""The Journey-driven path: an explicit Journey definition plus Fixture state
in, a normalized Trace retrieved after the conversation, Journey-specific
Assertions and Judge criteria over it.

Parallel to the payments path and free of it: loading and checking a Scenario
of a new Journey imports neither ``fixtures.paycard``, the payments Scenario
loader nor the mock. Running one does: ``simulated_user`` subclasses the
payments ``UserSimulator`` and ``episode`` reaches the Agent adapter package.
Contract: ``docs/plans/langgraph-harness.md``.
"""
