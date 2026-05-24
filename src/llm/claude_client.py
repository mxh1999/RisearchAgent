import asyncio
import json
import logging
import urllib.error
import urllib.request
from typing import Any, Optional

from src.config import LLMConfig
from src.llm.gpt_client import _loads_json_response

logger = logging.getLogger(__name__)


class ClaudeClient:
    """Anthropic-compatible messages client."""

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
        content = prompt
        if json_mode:
            content = f"{prompt}\n\nReturn only valid JSON."
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": 32768,
            "temperature": temperature,
            "messages": [{"role": "user", "content": content}],
        }

        async with self._semaphore:
            for attempt in range(max_retries):
                try:
                    return await asyncio.to_thread(self._post_message, payload)
                except Exception as e:
                    if attempt == max_retries - 1:
                        logger.error(
                            "Claude-compatible call failed after %s attempts: %s",
                            max_retries,
                            e,
                        )
                        raise
                    wait = 2 ** attempt
                    logger.warning(
                        "Claude-compatible attempt %s failed: %s, retrying in %ss",
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

    def _post_message(self, payload: dict[str, Any]) -> str:
        if not self.config.base_url:
            raise ValueError("llm.base_url is required for response_format='claude'")
        if not self.config.api_key:
            raise ValueError(f"{self.config.api_key_env} environment variable is not set")

        request = urllib.request.Request(
            _messages_url(self.config.base_url),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "x-api-key": self.config.api_key,
                "anthropic-version": "2023-06-01",
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
                f"Claude-compatible HTTP {exc.code}: {body[:500]}"
            ) from exc

        data = json.loads(body)
        return "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        )


def _messages_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/v1"):
        return f"{normalized}/messages"
    return f"{normalized}/v1/messages"
