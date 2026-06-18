"""
OpenAI LLM provider implementation.

Uses openai.AsyncOpenAI with JSON mode for structured output.
"""

import json

import structlog
from openai import AsyncOpenAI

from src.config import settings
from src.llm import ratelimit
from src.llm.base import LLMProvider

logger = structlog.get_logger()


class OpenAIProvider(LLMProvider):
    """OpenAI-backed LLM provider."""

    def __init__(self) -> None:
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_model

    async def structured_output(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict | None = None,
    ) -> dict:
        """Generate structured JSON output using OpenAI JSON mode."""
        # Append JSON instruction to system prompt
        json_instruction = (
            "\n\nYou MUST respond with valid JSON only. "
            "No markdown, no code fences, no extra text."
        )
        full_system = system_prompt + json_instruction

        logger.debug(
            "openai.structured_output",
            model=self._model,
            system_len=len(full_system),
            user_len=len(user_prompt),
        )

        await ratelimit.acquire()
        response = await self._client.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": full_system},
                {"role": "user", "content": user_prompt},
            ],
        )

        content = response.choices[0].message.content or "{}"
        logger.debug("openai.structured_output.done", response_len=len(content))

        return json.loads(content)

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Generate free-form text using OpenAI."""
        logger.debug(
            "openai.generate",
            model=self._model,
            system_len=len(system_prompt),
            user_len=len(user_prompt),
        )

        await ratelimit.acquire()
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )

        content = response.choices[0].message.content or ""
        logger.debug("openai.generate.done", response_len=len(content))

        return content
