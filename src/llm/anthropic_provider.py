"""
Anthropic LLM provider implementation.

Uses anthropic.AsyncAnthropic with system prompt JSON instructions
for structured output.
"""

import json

import structlog
from anthropic import AsyncAnthropic

from src.config import settings
from src.llm import ratelimit
from src.llm.base import LLMProvider

logger = structlog.get_logger()


class AnthropicProvider(LLMProvider):
    """Anthropic-backed LLM provider."""

    def __init__(self) -> None:
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_model

    async def structured_output(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict | None = None,
    ) -> dict:
        """Generate structured JSON output using Anthropic.

        Instructs the model via system prompt to return valid JSON only,
        then parses the response text.
        """
        json_instruction = (
            "\n\nYou MUST respond with valid JSON only. "
            "No markdown, no code fences, no extra text."
        )
        full_system = system_prompt + json_instruction

        logger.debug(
            "anthropic.structured_output",
            model=self._model,
            system_len=len(full_system),
            user_len=len(user_prompt),
        )

        await ratelimit.acquire()
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=full_system,
            messages=[
                {"role": "user", "content": user_prompt},
            ],
        )

        # Extract text from the first content block
        content = response.content[0].text if response.content else "{}"
        logger.debug("anthropic.structured_output.done", response_len=len(content))

        # Strip any accidental markdown fences
        text = content.strip()
        if text.startswith("```"):
            # Remove opening fence (e.g. ```json)
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        return json.loads(text)

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Generate free-form text using Anthropic."""
        logger.debug(
            "anthropic.generate",
            model=self._model,
            system_len=len(system_prompt),
            user_len=len(user_prompt),
        )

        await ratelimit.acquire()
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt},
            ],
        )

        content = response.content[0].text if response.content else ""
        logger.debug("anthropic.generate.done", response_len=len(content))

        return content
