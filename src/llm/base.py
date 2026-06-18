"""
Abstract base class for LLM providers.

All providers must implement structured_output() and generate().
"""

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Base class for LLM provider implementations."""

    @abstractmethod
    async def structured_output(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict | None = None,
    ) -> dict:
        """Generate structured JSON output.

        Args:
            system_prompt: Instructions for the model.
            user_prompt: The user's input / content to process.
            schema: Optional JSON schema hint for the expected output.

        Returns:
            Parsed JSON as a Python dict.
        """
        ...

    @abstractmethod
    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Generate free-form text.

        Args:
            system_prompt: Instructions for the model.
            user_prompt: The user's input.

        Returns:
            The generated text string.
        """
        ...
