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
        self._client = genai.Client(api_key=config.api_key)
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
        """Generate embeddings for a list of texts."""
        result = await self._client.aio.models.embed_content(
            model=self.config.embedding_model,
            contents=texts,
        )
        return [e.values for e in result.embeddings]
