"""
LLM provider factory.

Returns the configured LLM provider based on settings.llm_provider.
"""

import structlog

from src.config import settings
from src.llm.base import LLMProvider

logger = structlog.get_logger()


def get_llm_provider() -> LLMProvider:
    """Return the configured LLM provider instance.

    Reads settings.llm_provider to determine which provider to instantiate.
    Validates that the corresponding API key is configured.

    Returns:
        An instance of the selected LLMProvider implementation.

    Raises:
        ValueError: If the provider is unknown or its API key is missing.
    """
    provider_name = settings.llm_provider.lower()

    if provider_name == "openai":
        if not settings.openai_api_key:
            raise ValueError(
                "OpenAI API key not configured. Set OPENAI_API_KEY in .env"
            )
        from src.llm.openai_provider import OpenAIProvider

        logger.info("llm.provider_selected", provider="openai", model=settings.openai_model)
        return OpenAIProvider()

    elif provider_name == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError(
                "Anthropic API key not configured. Set ANTHROPIC_API_KEY in .env"
            )
        from src.llm.anthropic_provider import AnthropicProvider

        logger.info("llm.provider_selected", provider="anthropic", model=settings.anthropic_model)
        return AnthropicProvider()

    elif provider_name == "gemini":
        if not settings.gemini_api_key:
            raise ValueError(
                "Gemini API key not configured. Set GEMINI_API_KEY in .env"
            )
        from src.llm.gemini_provider import GeminiProvider

        logger.info("llm.provider_selected", provider="gemini", model=settings.gemini_model)
        return GeminiProvider()

    else:
        raise ValueError(
            f"Unknown LLM provider: '{provider_name}'. "
            f"Supported providers: openai, anthropic, gemini"
        )
