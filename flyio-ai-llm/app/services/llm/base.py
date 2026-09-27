"""Abstract base class for LLM providers."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseLLMProvider(ABC):
    """Protocol / interface for LLM text completion/chat providers."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        context: Optional[str] = None,
        system_prompt: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Generate response given a user prompt, optional context, and system instructions.
        
        Note on system_prompt: When system_prompt is None (or omitted), provider implementations
        must fall back to their default system prompt behavior (e.g. standard system instructions).
        """
        pass
