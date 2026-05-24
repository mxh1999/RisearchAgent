import json
from pathlib import Path

import pytest
import yaml

from src.config import load_config


def test_load_config_reads_custom_gpt_provider(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("RISEARCHAGENT_API_KEY", "test-key")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "topics": [
                    {
                        "name": "Topic",
                        "query": "test",
                        "categories": ["cs.AI"],
                        "research_profile": "profile",
                    }
                ],
                "llm": {
                    "response_format": "gpt",
                    "base_url": "https://api.example.com",
                    "api_key_env": "RISEARCHAGENT_API_KEY",
                    "filter_model": "gpt-5.5",
                    "reader_model": "gpt-5.5",
                    "embedding_model": "legacy-unused",
                },
            }
        ),
        encoding="utf-8",
    )

    config = load_config(str(config_path))

    assert config.llm.response_format == "gpt"
    assert config.llm.base_url == "https://api.example.com"
    assert config.llm.api_key_env == "RISEARCHAGENT_API_KEY"
    assert config.llm.api_key == "test-key"


def test_create_llm_client_uses_gpt_client() -> None:
    from src.config import LLMConfig
    from src.llm.client import create_llm_client
    from src.llm.gpt_client import GPTClient

    client = create_llm_client(
        LLMConfig(
            filter_model="gpt-5.5",
            reader_model="gpt-5.5",
            embedding_model="legacy-unused",
            api_key="test-key",
            max_concurrent=1,
            temperature=0.1,
            response_format="gpt",
            base_url="https://api.example.com",
            api_key_env="RISEARCHAGENT_API_KEY",
        )
    )

    assert isinstance(client, GPTClient)


@pytest.mark.asyncio
async def test_gpt_client_posts_chat_completion_and_parses_text(monkeypatch) -> None:
    from src.config import LLMConfig
    from src.llm.gpt_client import GPTClient

    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode("utf-8"))

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(
                    {
                        "choices": [
                            {"message": {"content": "{\"ok\": true}"}}
                        ]
                    }
                ).encode("utf-8")

        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    client = GPTClient(
        LLMConfig(
            filter_model="gpt-5.5",
            reader_model="gpt-5.5",
            embedding_model="legacy-unused",
            api_key="test-key",
            max_concurrent=1,
            temperature=0.2,
            response_format="gpt",
            base_url="https://api.example.com",
            api_key_env="RISEARCHAGENT_API_KEY",
        )
    )

    text = await client.generate("Return JSON.", model="gpt-5.5", json_mode=True)

    assert text == "{\"ok\": true}"
    assert captured["url"] == "https://api.example.com/v1/chat/completions"
    assert captured["payload"]["model"] == "gpt-5.5"
    assert captured["payload"]["messages"] == [
        {"role": "user", "content": "Return JSON."}
    ]
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["headers"]["User-agent"] == "RisearchAgent/1.0"


@pytest.mark.asyncio
async def test_gpt_client_generate_json_strips_code_fences(monkeypatch) -> None:
    from src.config import LLMConfig
    from src.llm.gpt_client import GPTClient

    def fake_urlopen(request, timeout):
        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": "```json\n{\"ok\": true}\n```"
                                }
                            }
                        ]
                    }
                ).encode("utf-8")

        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    client = GPTClient(
        LLMConfig(
            filter_model="gpt-5.5",
            reader_model="gpt-5.5",
            embedding_model="legacy-unused",
            api_key="test-key",
            max_concurrent=1,
            temperature=0.2,
            response_format="gpt",
            base_url="https://api.example.com",
            api_key_env="RISEARCHAGENT_API_KEY",
        )
    )

    assert await client.generate_json("Return JSON.") == {"ok": True}
