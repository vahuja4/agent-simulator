from .base import AgentAdapter
from .mock_paycard import MockConfig, MockPayCardAgent

# "http" arrives in Phase 5 (HTTPAgentAdapter → Sierra).
ADAPTERS = {
    "mock": MockPayCardAgent,
}

__all__ = ["AgentAdapter", "MockPayCardAgent", "MockConfig", "ADAPTERS"]
