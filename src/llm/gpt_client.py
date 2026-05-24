import asyncio
import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any, Optional

from src.config import LLMConfig

logger = logging.getLogger(__name__)


class GPTClient:
    """OpenAI-compatible chat completion client."""

    def __init__(self, config: LLMConfig):
        self.config = config
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
        model = model or self.config.filter_model
        temperature = temperature if temperature is not None else self.config.temperature

        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        async with self._semaphore:
            for attempt in range(max_retries):
                try:
                    return await asyncio.to_thread(self._post_chat_completion, payload)
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.error(
                            "GPT-compatible call failed after %s attempts: %s",
                            max_retries,
                            e,
                        )
                        raise
                    wait = 2 ** attempt
                    logger.warning(
                        "GPT-compatible attempt %s failed: %s, retrying in %ss",
                        attempt + 1,
                        e,
                        wait,
                    )
                    await asyncio.sleep(wait)

    async def generate_json(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        text = await self.generate(
            prompt,
            model=model,
            temperature=temperature,
            json_mode=True,
        )
        return _loads_json_response(text)

    def _post_chat_completion(self, payload: dict[str, Any]) -> str:
        if not self.config.base_url:
            raise ValueError("llm.base_url is required for response_format='gpt'")
        if not self.config.api_key:
            raise ValueError(f"{self.config.api_key_env} environment variable is not set")

        request = urllib.request.Request(
            _chat_completions_url(self.config.base_url),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "RisearchAgent/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"GPT-compatible HTTP {exc.code}: {body[:500]}"
            ) from exc

        data = json.loads(body)
        return data["choices"][0]["message"]["content"]


def _chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return f"{normalized}/v1/chat/completions"


def _loads_json_response(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\}|\[.*\])", cleaned, flags=re.DOTALL)
        if match:
            return json.loads(match.group(1))
        raise
