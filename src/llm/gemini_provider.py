"""
Google Gemini LLM provider implementation.

Uses google.genai.Client (google-genai package) with async generation.
"""

import json

import structlog
from google import genai
from google.genai import types

from src.config import settings
from src.llm import ratelimit
from src.llm.base import LLMProvider

logger = structlog.get_logger()


class GeminiProvider(LLMProvider):
    """Google Gemini-backed LLM provider."""

    def __init__(self) -> None:
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._model = settings.gemini_model

    async def structured_output(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict | None = None,
    ) -> dict:
        """Generate structured JSON output using Gemini with JSON mime type."""
        logger.debug(
            "gemini.structured_output",
            model=self._model,
            system_len=len(system_prompt),
            user_len=len(user_prompt),
        )

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
        )

        await ratelimit.acquire()
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=user_prompt,
            config=config,
        )

        content = response.text or "{}"
        logger.debug("gemini.structured_output.done", response_len=len(content))

        return json.loads(content)

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Generate free-form text using Gemini."""
        logger.debug(
            "gemini.generate",
            model=self._model,
            system_len=len(system_prompt),
            user_len=len(user_prompt),
        )

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
        )

        await ratelimit.acquire()
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=user_prompt,
            config=config,
        )

        content = response.text or ""
        logger.debug("gemini.generate.done", response_len=len(content))

        return content
