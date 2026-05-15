import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from run import build_parser


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
