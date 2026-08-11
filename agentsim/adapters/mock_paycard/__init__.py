"""MockPayCardAgent — a deterministic, rule-based state machine over fixture
data covering all five PayCard journeys. No LLM calls in here, ever: given
the same conversation it produces the same replies, tool calls, and results,
which is what makes the flows unit-testable offline and the planted defects
reproducible.

Package layout: one module per journey (j1–j5), shared per-conversation state
in ``state``, text parsing + journey routing in ``parsing``, the defect flags
in ``config``, and the agent/dispatcher in ``agent``. The public import path
is unchanged from Phase 1: ``agentsim.adapters.mock_paycard``.

The seven planted defects (design §6, D1–D7) live INLINE in the journey
modules, each gated on a MockConfig flag at the exact point the faithful code
path runs — search for ``# D<n>:`` comments. All flags default False.
"""

from .agent import MockPayCardAgent
from .config import MockConfig
from .state import PendingPayment

__all__ = ["MockPayCardAgent", "MockConfig", "PendingPayment"]
