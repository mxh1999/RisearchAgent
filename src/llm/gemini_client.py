import asyncio
import json
import logging
from typing import Any, Optional

from google import genai

from src.config import LLMConfig

logger = logging.getLogger(__name__)


class GeminiClient:
    """Unified Gemini client with JSON mode, retry, and concurrency control."""

    def __init__(self, config: LLMConfig):
        self.config = config

        # Primary client: text generation (chat completions / generateContent).
        chat_kwargs: dict = {"api_key": config.api_key}
        if config.base_url:
            chat_kwargs["http_options"] = genai.types.HttpOptions(
                base_url=config.base_url
            )
        self._client = genai.Client(**chat_kwargs)

        # Optional secondary client for embeddings, when the chat provider
        # doesn't expose an embedding model. If embedding_api_key is unset,
        # embed() reuses self._client.
        if config.embedding_api_key:
            embed_kwargs: dict = {"api_key": config.embedding_api_key}
            if config.embedding_base_url:
                embed_kwargs["http_options"] = genai.types.HttpOptions(
                    base_url=config.embedding_base_url
                )
            self._embed_client = genai.Client(**embed_kwargs)
        else:
            self._embed_client = self._client

        self._semaphore = asyncio.Semaphore(config.max_concurrent)

    async def generate(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        json_mode: bool = False,
        max_retries: int = 3,
    ) -> str:
        """Generate text with retry and concurrency control."""
        model = model or self.config.filter_model
        temperature = temperature if temperature is not None else self.config.temperature

        gen_config = genai.types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=32768,
        )
        if json_mode:
            gen_config.response_mime_type = "application/json"

        async with self._semaphore:
            for attempt in range(max_retries):
                try:
                    response = await self._client.aio.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=gen_config,
                    )
                    return response.text
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.error(f"Gemini call failed after {max_retries} attempts: {e}")
                        raise
                    wait = 2 ** attempt
                    logger.warning(f"Gemini attempt {attempt + 1} failed: {e}, retrying in {wait}s")
                    await asyncio.sleep(wait)

    async def generate_json(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        """Generate and parse JSON response."""
        text = await self.generate(
            prompt, model=model, temperature=temperature, json_mode=True
        )
        return json.loads(text)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts.

        Routes to self._embed_client which may be a separate (key, base_url)
        when the chat provider doesn't expose an embedding model.
        """
        result = await self._embed_client.aio.models.embed_content(
            model=self.config.embedding_model,
            contents=texts,
        )
        return [e.values for e in result.embeddings]
