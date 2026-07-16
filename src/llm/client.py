from __future__ import annotations

import os
from typing import Any, Optional, Protocol

from src.config import (
    DEFAULT_LLM_API_KEY_ENV,
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_RESPONSE_FORMAT,
    LLMConfig,
)


class LLMClient(Protocol):
    async def generate(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        json_mode: bool = False,
        max_retries: int = 3,
    ) -> str:
        ...

    async def generate_json(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        ...


def create_llm_client(config: LLMConfig) -> LLMClient:
    response_format = config.response_format.lower()
    if response_format == "gemini":
        from src.llm.gemini_client import GeminiClient

        return GeminiClient(config)
    if response_format == "gpt":
        from src.llm.gpt_client import GPTClient

        return GPTClient(config)
    if response_format == "claude":
        from src.llm.claude_client import ClaudeClient

        return ClaudeClient(config)
    raise ValueError(f"Unsupported LLM response_format: {config.response_format}")


def normalize_llm_config(config) -> LLMConfig:
    """Return a complete LLMConfig from real config or test doubles."""
    response_format = getattr(
        config, "response_format", DEFAULT_LLM_RESPONSE_FORMAT
    )
    default_api_key_env = (
        "GEMINI_API_KEY"
        if response_format == "gemini"
        else DEFAULT_LLM_API_KEY_ENV
    )
    api_key_env = getattr(config, "api_key_env", default_api_key_env)
    api_key = getattr(config, "api_key", "") or os.environ.get(api_key_env, "")
    return LLMConfig(
        filter_model=getattr(config, "filter_model"),
        reader_model=getattr(config, "reader_model"),
        embedding_model=getattr(config, "embedding_model", ""),
        api_key=api_key,
        max_concurrent=getattr(config, "max_concurrent", 5),
        temperature=getattr(config, "temperature", 0.3),
        response_format=response_format,
        base_url=getattr(config, "base_url", DEFAULT_LLM_BASE_URL),
        api_key_env=api_key_env,
    )
