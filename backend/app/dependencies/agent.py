"""Agent dependency management."""
from typing import Annotated
from fastapi import Depends

from ..core.langgraph.agent import NoraAgent


# Global agent instance - initialized at startup
_agent_instance: NoraAgent | None = None


def init_agent() -> None:
    """Initialize the global agent instance."""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = NoraAgent()


def get_agent() -> NoraAgent:
    """Get the agent instance."""
    if _agent_instance is None:
        raise RuntimeError("Agent not initialized")
    return _agent_instance


# Type alias for cleaner dependency injection
AgentDep = Annotated[NoraAgent, Depends(get_agent)]