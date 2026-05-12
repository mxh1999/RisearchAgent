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
