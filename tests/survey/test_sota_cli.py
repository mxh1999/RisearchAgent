from __future__ import annotations

import asyncio
import json
import textwrap
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from run import build_parser
from src.reader.staged_models import (
    Evidence,
    ExperimentRecord,
    PaperReadingPackage,
)
from src.survey.sota_cli import cmd_sota_update


def _write_topic(topic_dir: Path, topic_id: str = "utility_nav") -> Path:
    topic_dir.mkdir(parents=True, exist_ok=True)
    topic_path = topic_dir / "topic.yaml"
    topic_path.write_text(
        textwrap.dedent(
            f"""
            # Human note should survive.
            topic_id: {topic_id}
            name: Utility Navigation
            description: Task-conditioned utility over 3D memory.
            intent: Maintain comparable SOTA tables.
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return topic_path


def _write_package(topic_dir: Path) -> None:
    package = PaperReadingPackage(
        paper_id="paper-1",
        title="Paper One",
        source_path="paper-1.pdf",
        experiments=[
            ExperimentRecord(
                benchmark="GOAT-Bench",
                setting="val unseen",
                metric="SPL",
                method="SampleNav",
                value=35.1,
                higher_is_better=True,
                source=Evidence(
                    text="SPL result",
                    page=8,
                    section="Experiments",
                    quote="SampleNav obtains 35.1 SPL.",
                    confidence="high",
                ),
            )
        ],
    )
    papers_dir = topic_dir / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)
    (papers_dir / "paper-1.json").write_text(
        json.dumps(package.to_dict()), encoding="utf-8"
    )


def test_sota_update_parser_and_legacy_show_mode() -> None:
    parser = build_parser()

    update_args = parser.parse_args(
        [
            "sota",
            "update",
            "--topic",
            "data/topics/utility_nav/topic.yaml",
            "--no-llm-normalize",
        ]
    )
    show_args = parser.parse_args(["sota"])

    assert update_args.command == "sota"
    assert update_args.sota_command == "update"
    assert update_args.topic == "data/topics/utility_nav/topic.yaml"
    assert update_args.no_llm_normalize is True
    assert show_args.command == "sota"
    assert show_args.sota_command is None


def test_sota_update_writes_artifacts_and_preserves_topic_yaml(
    tmp_path: Path,
) -> None:
    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    original_yaml = topic_path.read_text(encoding="utf-8")
    _write_package(topic_dir)
    (topic_dir / "sota.md").write_text(
        "# Utility Navigation SOTA\n\nManual notes.\n\n"
        "<!-- BEGIN AUTO:sota -->\nOld SOTA\n<!-- END AUTO:sota -->\n",
        encoding="utf-8",
    )

    asyncio.run(
        cmd_sota_update(
            SimpleNamespace(
                topic=str(topic_path),
                readings_dir=None,
                no_llm_normalize=True,
                config="config.yaml",
            )
        )
    )

    assert topic_path.read_text(encoding="utf-8") == original_yaml
    sota_md = (topic_dir / "sota.md").read_text(encoding="utf-8")
    records_jsonl = (topic_dir / "state" / "sota_records.jsonl").read_text(
        encoding="utf-8"
    )
    groups_json = (topic_dir / "state" / "sota_setting_groups.json").read_text(
        encoding="utf-8"
    )
    assert "Manual notes." in sota_md
    assert "Old SOTA" not in sota_md
    assert "SampleNav" in sota_md
    assert "paper-1::GOAT-Bench::val unseen::SPL::SampleNav" in records_jsonl
    assert "goat_bench_val_unseen" in groups_json
    assert not (topic_dir / "survey.md").exists()
    assert not (topic_dir / "papers.md").exists()
    assert not (topic_dir / "positioning.md").exists()
    assert not (topic_dir / "references.md").exists()


def test_sota_update_rejects_topic_id_mismatch_before_writes(tmp_path: Path) -> None:
    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir, topic_id="other_topic")
    _write_package(topic_dir)

    with pytest.raises(SystemExit, match="topic_id"):
        asyncio.run(
            cmd_sota_update(
                SimpleNamespace(
                    topic=str(topic_path),
                    readings_dir=None,
                    no_llm_normalize=True,
                    config="config.yaml",
                )
            )
        )

    assert not (topic_dir / "sota.md").exists()
    assert not (topic_dir / "state" / "sota_records.jsonl").exists()


def test_sota_update_rejects_no_experiment_records(tmp_path: Path) -> None:
    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    papers_dir = topic_dir / "papers"
    papers_dir.mkdir(parents=True)
    package = PaperReadingPackage(
        paper_id="paper-1",
        title="Paper One",
        source_path="paper-1.pdf",
    )
    (papers_dir / "paper-1.json").write_text(
        json.dumps(package.to_dict()), encoding="utf-8"
    )

    with pytest.raises(SystemExit, match="No experiment records"):
        asyncio.run(
            cmd_sota_update(
                SimpleNamespace(
                    topic=str(topic_path),
                    readings_dir=None,
                    no_llm_normalize=True,
                    config="config.yaml",
                )
            )
        )

    assert not (topic_dir / "sota.md").exists()


def test_sota_update_validates_local_inputs_before_api_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr("src.survey.sota_cli.load_dotenv", lambda: None)
    monkeypatch.setattr(
        "src.survey.sota_cli.load_config",
        lambda path: SimpleNamespace(
            llm=SimpleNamespace(
                filter_model="filter-model",
                reader_model="reader-model",
                embedding_model="embedding-model",
                api_key="",
                max_concurrent=1,
                temperature=0.1,
            )
        ),
    )
    args = SimpleNamespace(
        topic=str(tmp_path / "missing" / "topic.yaml"),
        readings_dir=None,
        no_llm_normalize=False,
        config="config.yaml",
    )

    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(cmd_sota_update(args))

    message = str(exc_info.value)
    assert "topic YAML" in message
    assert "GEMINI_API_KEY" not in message


def test_sota_update_uses_fake_llm_for_canonicalization(tmp_path: Path, monkeypatch) -> None:
    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    _write_package(topic_dir)

    class FakeGeminiClient:
        def __init__(self, config) -> None:
            self.config = config

        async def generate_json(self, prompt, model=None, temperature=None):
            return {
                "action": "create_new",
                "canonical_benchmark": "GOAT-Bench",
                "canonical_setting": "val unseen, standard protocol",
                "comparison_axes": {"split": "val unseen"},
                "confidence": "high",
                "rationale": "Standard validation split.",
            }

    fake_module = types.ModuleType("src.llm.gemini_client")
    fake_module.GeminiClient = FakeGeminiClient
    monkeypatch.setitem(__import__("sys").modules, "src.llm.gemini_client", fake_module)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        "src.survey.sota_cli.load_config",
        lambda path: SimpleNamespace(
            llm=SimpleNamespace(
                filter_model="filter-model",
                reader_model="reader-model",
                embedding_model="embedding-model",
                api_key="",
                max_concurrent=1,
                temperature=0.1,
            )
        ),
    )

    asyncio.run(
        cmd_sota_update(
            SimpleNamespace(
                topic=str(topic_path),
                readings_dir=None,
                no_llm_normalize=False,
                config="config.yaml",
            )
        )
    )

    assert "val unseen, standard protocol" in (
        topic_dir / "sota.md"
    ).read_text(encoding="utf-8")


def test_topic_artifact_ensure_does_not_create_sota_by_default(tmp_path: Path) -> None:
    from src.survey.artifacts import TopicArtifactManager
    from src.survey.models import TopicProfile

    manager = TopicArtifactManager(tmp_path)
    manager.ensure_topic_artifacts(
        TopicProfile(
            topic_id="utility_nav",
            name="Utility Navigation",
            description="Task-conditioned utility.",
            intent="Build survey artifacts.",
        )
    )

    assert not (tmp_path / "utility_nav" / "sota.md").exists()


def test_sota_update_cached_settings_do_not_require_api_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    _write_package(topic_dir)
    state_dir = topic_dir / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "sota_setting_groups.json").write_text(
        json.dumps(
            {
                "groups": [
                    {
                        "group_id": "goat_bench_val_unseen",
                        "canonical_benchmark": "GOAT-Bench",
                        "canonical_setting": "val unseen",
                        "raw_benchmark_settings": [
                            {"benchmark": "GOAT-Bench", "setting": "val unseen"}
                        ],
                        "comparison_axes": {"split": "val unseen"},
                        "confidence": "high",
                        "rationale": "Cached setting group.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr("src.survey.sota_cli.load_dotenv", lambda: None)
    monkeypatch.setattr(
        "src.survey.sota_cli.load_config",
        lambda path: pytest.fail("load_config should not be called for cached settings"),
    )

    asyncio.run(
        cmd_sota_update(
            SimpleNamespace(
                topic=str(topic_path),
                readings_dir=None,
                no_llm_normalize=False,
                config="config.yaml",
            )
        )
    )

    assert "SampleNav" in (topic_dir / "sota.md").read_text(encoding="utf-8")
