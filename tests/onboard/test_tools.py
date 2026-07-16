from types import SimpleNamespace

import yaml

from src.onboard.tools import OnboardTools


def test_save_onboard_result_uses_gpt_defaults_without_embeddings(tmp_path) -> None:
    config_path = tmp_path / "config.yaml"
    tools = OnboardTools(
        llm=SimpleNamespace(),
        llm_config=SimpleNamespace(),
        config_path=str(config_path),
        pdf_dir=tmp_path / "pdfs",
        sota_dir=tmp_path / "sota",
    )

    tools.save_onboard_result(
        research_profile="LLM-based research workflows",
        topics=[
            {
                "name": "Research Agents",
                "query": "research agents",
                "categories": ["cs.AI"],
            }
        ],
        relevance_threshold=6,
        anchor_paper_ids=[],
        classic_baselines=[],
    )

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert raw["llm"] == {
        "response_format": "gpt",
        "base_url": "https://api.ikuncode.cc",
        "api_key_env": "RISEARCHAGENT_API_KEY",
        "filter_model": "gpt-5.6-sol",
        "reader_model": "gpt-5.6-sol",
        "max_concurrent": 5,
        "temperature": 0.3,
    }
    assert "chroma_path" not in raw
