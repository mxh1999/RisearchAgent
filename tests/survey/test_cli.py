import asyncio
import json
import subprocess
import sys
import textwrap
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from run import build_parser
from src.reader.staged_models import PaperReadingPackage, PaperSummary, TopicRelation
from src.survey.cli import _load_topic, cmd_survey_synthesize


def test_survey_refine_from_note_sets_note_input() -> None:
    args = build_parser().parse_args(
        [
            "survey",
            "refine",
            "--from-note",
            "2026-05-11_21-32-21_thesis_direction_brainstorm.md",
        ]
    )

    assert args.command == "survey"
    assert args.survey_command == "refine"
    assert args.from_note == "2026-05-11_21-32-21_thesis_direction_brainstorm.md"
    assert args.topic_text is None


def test_survey_refine_topic_text_sets_text_input() -> None:
    args = build_parser().parse_args(
        ["survey", "refine", "task-conditioned 3D utility learning"]
    )

    assert args.topic_text == "task-conditioned 3D utility learning"


def test_survey_refine_requires_input() -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["survey", "refine"])

    assert exc_info.value.code == 2


def test_survey_refine_rejects_both_text_and_note() -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(
            ["survey", "refine", "topic", "--from-note", "note.md"]
        )

    assert exc_info.value.code == 2


def test_survey_synthesize_requires_topic() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["survey", "synthesize"])

    assert exc_info.value.code == 2


def test_survey_synthesize_accepts_topic_and_readings_dir() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "survey",
            "synthesize",
            "--topic",
            "data/topics/topic/topic.yaml",
            "--readings-dir",
            "data/readings",
        ]
    )

    assert args.command == "survey"
    assert args.survey_command == "synthesize"
    assert args.topic == "data/topics/topic/topic.yaml"
    assert args.readings_dir == "data/readings"


def test_load_topic_rejects_missing_file(tmp_path) -> None:
    path = tmp_path / "missing.yaml"

    with pytest.raises(SystemExit, match="not found"):
        _load_topic(path)


def test_load_topic_rejects_empty_yaml(tmp_path) -> None:
    path = tmp_path / "topic.yaml"
    path.write_text("", encoding="utf-8")

    with pytest.raises(SystemExit, match="empty YAML"):
        _load_topic(path)


def test_load_topic_rejects_non_mapping_yaml(tmp_path) -> None:
    path = tmp_path / "topic.yaml"
    path.write_text("- not\n- mapping\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="expected mapping object"):
        _load_topic(path)


def test_load_topic_rejects_malformed_topic_profile(tmp_path) -> None:
    path = tmp_path / "topic.yaml"
    path.write_text("topic_id: missing_fields\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="malformed TopicProfile"):
        _load_topic(path)


def test_survey_synthesize_rejects_topic_id_path_mismatch_before_writes(
    tmp_path, monkeypatch
) -> None:
    topic_dir = tmp_path / "foo"
    topic_dir.mkdir()
    topic_path = topic_dir / "topic.yaml"
    topic_path.write_text(
        textwrap.dedent(
            """
            topic_id: bar
            name: Bar Topic
            description: Topic description.
            intent: Build a survey.
            """
        ).lstrip(),
        encoding="utf-8",
    )

    class FakeGeminiClient:
        def __init__(self, config) -> None:
            self.config = config

    fake_gemini_module = types.ModuleType("src.llm.gemini_client")
    fake_gemini_module.GeminiClient = FakeGeminiClient
    monkeypatch.setitem(sys.modules, "src.llm.gemini_client", fake_gemini_module)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        "src.survey.cli.load_config",
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
        config="config.yaml",
        topic=str(topic_path),
        readings_dir=None,
    )

    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(cmd_survey_synthesize(args))

    message = str(exc_info.value)
    assert "topic_id" in message
    assert "bar" in message
    assert "foo" in message
    assert not (tmp_path / "bar").exists()
    assert not (topic_dir / "survey.md").exists()


def test_survey_synthesize_reports_missing_topic_before_api_key(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr("src.survey.cli.load_dotenv", lambda: None)
    monkeypatch.setattr(
        "src.survey.cli.load_config",
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
        config="config.yaml",
        topic=str(tmp_path / "missing" / "topic.yaml"),
        readings_dir=None,
    )

    with pytest.raises(SystemExit) as exc_info:
        asyncio.run(cmd_survey_synthesize(args))

    message = str(exc_info.value)
    assert "topic YAML" in message
    assert "not found" in message
    assert "GEMINI_API_KEY" not in message
    assert "google-genai" not in message


def test_survey_synthesize_preserves_topic_yaml_bytes(tmp_path, monkeypatch) -> None:
    topic_dir = tmp_path / "utility_nav"
    papers_dir = topic_dir / "papers"
    papers_dir.mkdir(parents=True)
    topic_path = topic_dir / "topic.yaml"
    original_topic_yaml = textwrap.dedent(
        """
        # Keep this human note.
        topic_id: utility_nav
        name: Utility Navigation
        description: Task-conditioned utility over 3D memory.
        intent: Find a thesis gap.
        custom_note: should survive synthesize
        """
    ).lstrip()
    topic_path.write_text(original_topic_yaml, encoding="utf-8")
    package = PaperReadingPackage(
        paper_id="paper-1",
        title="Paper One",
        source_path="paper-1.pdf",
        summary=PaperSummary(
            problem="Navigation requires decisions.",
            method="Scores candidates.",
            takeaway="Relevant to utility learning.",
            contributions=["Candidate scoring"],
        ),
        topic_relation=TopicRelation(
            relevance="core",
            concept_axes=["utility"],
            collision_risk="low",
            differentiation="Uses explicit scoring.",
        ),
    )
    (papers_dir / "paper-1.json").write_text(
        json.dumps(package.to_dict()), encoding="utf-8"
    )

    class FakeGeminiClient:
        def __init__(self, config) -> None:
            self.config = config

        async def generate_json(self, prompt, model=None, temperature=None):
            return {
                "taxonomy": [
                    {
                        "name": "Explicit utility",
                        "description": "Score candidate actions.",
                        "paper_ids": ["paper-1"],
                        "key_distinction": "Uses decision scores.",
                    }
                ],
                "paper_map": [
                    {
                        "paper_id": "paper-1",
                        "title": "Paper One",
                        "role": "core",
                        "rationale": "Directly relevant.",
                        "evidence": "Candidate scoring.",
                    }
                ],
                "positioning": {
                    "thesis_gap": "General 3D utility.",
                    "novelty_claim": "Explicit utility over richer primitives.",
                    "collision_risks": ["Baseline overlap."],
                    "recommended_positioning": "Generalize utility learning.",
                },
                "references": [
                    {
                        "paper_id": "paper-1",
                        "title": "Paper One",
                        "why_relevant": "Core paper.",
                        "evidence": "Candidate scoring.",
                    }
                ],
                "open_questions": ["How is utility supervised?"],
            }

    fake_gemini_module = types.ModuleType("src.llm.gemini_client")
    fake_gemini_module.GeminiClient = FakeGeminiClient
    monkeypatch.setitem(sys.modules, "src.llm.gemini_client", fake_gemini_module)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        "src.survey.cli.load_config",
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
        config="config.yaml",
        topic=str(topic_path),
        readings_dir=None,
    )

    asyncio.run(cmd_survey_synthesize(args))

    assert topic_path.read_text(encoding="utf-8") == original_topic_yaml
    assert "Explicit utility" in (topic_dir / "survey.md").read_text(
        encoding="utf-8"
    )


def test_survey_cli_import_does_not_require_google_genai() -> None:
    repo_root = Path(__file__).parents[2]
    code = textwrap.dedent(
        """
        import importlib.abc
        import sys

        class BlockGoogle(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "google" or fullname.startswith("google."):
                    raise ModuleNotFoundError("blocked google-genai")
                return None

        sys.meta_path.insert(0, BlockGoogle())
        import src.survey.cli
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
