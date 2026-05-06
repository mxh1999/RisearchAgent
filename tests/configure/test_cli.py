"""CLI loop tests using stub input/output functions for determinism."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
import yaml

from src.configure.cli import run_configure


def _scripted_input(answers: list[str]):
    """Yields each answer in order. Raises if exhausted."""
    it: Iterator[str] = iter(answers)

    def _input(prompt: str) -> str:
        try:
            return next(it)
        except StopIteration:
            raise AssertionError(f"input_fn ran out of scripted answers; prompt={prompt!r}")

    return _input


def _capture_output():
    captured: list[str] = []

    def _out(text: str) -> None:
        captured.append(text)

    return captured, _out


# —————————————————————————————————————————————————————————————
# Happy path
# —————————————————————————————————————————————————————————————


def test_enter_accepts_defaults_and_writes_config(fm, tmp_path: Path):
    target = tmp_path / "config.yaml"
    captured, out = _capture_output()
    derived = run_configure(
        fm,
        state=None,
        intent_text="testing",
        config_path=target,
        input_fn=_scripted_input([""]),  # just press Enter
        output_fn=out,
    )
    assert target.exists()
    assert len(derived["topics"]) == 1
    assert derived["filter"]["relevance_threshold"] == 6
    # Summary printed at least once
    assert any("Field Map Summary" in line for line in captured)


def test_q_quits_without_writing(fm, tmp_path: Path):
    target = tmp_path / "config.yaml"
    captured, out = _capture_output()
    derived = run_configure(
        fm,
        state=None,
        intent_text="testing",
        config_path=target,
        input_fn=_scripted_input(["q"]),
        output_fn=out,
    )
    assert derived == {}
    assert not target.exists()
    assert any("Aborted" in line for line in captured)


# —————————————————————————————————————————————————————————————
# Edit mode
# —————————————————————————————————————————————————————————————


def test_edit_then_accept_writes_modified_config(fm, tmp_path: Path):
    target = tmp_path / "config.yaml"
    _, out = _capture_output()
    answers = [
        "e",            # enter edit mode
        "threshold 8",  # change threshold
        "accept",       # write
    ]
    derived = run_configure(
        fm, state=None, intent_text="t", config_path=target,
        input_fn=_scripted_input(answers), output_fn=out,
    )
    assert derived["filter"]["relevance_threshold"] == 8
    assert target.exists()


def test_edit_drop_then_accept_excludes_subarea(fm, tmp_path: Path):
    target = tmp_path / "config.yaml"
    _, out = _capture_output()
    answers = [
        "e",
        "drop vln-ce",
        "accept",
    ]
    derived = run_configure(
        fm, state=None, intent_text="t", config_path=target,
        input_fn=_scripted_input(answers), output_fn=out,
    )
    assert derived["topics"] == []


def test_edit_rename_overrides_topic_name(fm, tmp_path: Path):
    target = tmp_path / "config.yaml"
    _, out = _capture_output()
    answers = [
        "e",
        'rename vln-ce "VLN-CE Custom"',
        "accept",
    ]
    derived = run_configure(
        fm, state=None, intent_text="t", config_path=target,
        input_fn=_scripted_input(answers), output_fn=out,
    )
    assert derived["topics"][0]["name"] == "VLN-CE Custom"


def test_edit_cancel_returns_to_top_then_quit(fm, tmp_path: Path):
    target = tmp_path / "config.yaml"
    _, out = _capture_output()
    answers = [
        "e",
        "threshold 8",
        "cancel",  # back to top
        "q",       # quit without writing
    ]
    derived = run_configure(
        fm, state=None, intent_text="t", config_path=target,
        input_fn=_scripted_input(answers), output_fn=out,
    )
    assert derived == {}
    assert not target.exists()


def test_edit_unknown_command_shows_error_and_continues(fm, tmp_path: Path):
    target = tmp_path / "config.yaml"
    captured, out = _capture_output()
    answers = [
        "e",
        "bogus-command",  # error, doesn't crash
        "accept",
    ]
    derived = run_configure(
        fm, state=None, intent_text="t", config_path=target,
        input_fn=_scripted_input(answers), output_fn=out,
    )
    assert derived  # successful accept
    assert any("unknown command" in line for line in captured)


def test_edit_invalid_threshold_shows_error_does_not_apply(fm, tmp_path: Path):
    target = tmp_path / "config.yaml"
    captured, out = _capture_output()
    answers = [
        "e",
        "threshold 99",  # rejected by session validator
        "accept",
    ]
    derived = run_configure(
        fm, state=None, intent_text="t", config_path=target,
        input_fn=_scripted_input(answers), output_fn=out,
    )
    # threshold stayed at default 6
    assert derived["filter"]["relevance_threshold"] == 6
    assert any("error" in line.lower() for line in captured)


def test_top_level_unknown_choice_loops_then_accepts(fm, tmp_path: Path):
    target = tmp_path / "config.yaml"
    _, out = _capture_output()
    answers = [
        "huh?",
        "",  # Enter accepts
    ]
    derived = run_configure(
        fm, state=None, intent_text="t", config_path=target,
        input_fn=_scripted_input(answers), output_fn=out,
    )
    assert derived
    assert target.exists()


# —————————————————————————————————————————————————————————————
# Roundtrip via YAML
# —————————————————————————————————————————————————————————————


def test_roundtrip_yaml_loadable(fm, tmp_path: Path):
    target = tmp_path / "config.yaml"
    _, out = _capture_output()
    run_configure(
        fm, state=None, intent_text="t", config_path=target,
        input_fn=_scripted_input([""]), output_fn=out,
    )
    loaded = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert "topics" in loaded
    assert "filter" in loaded
    assert "llm" in loaded  # default section
    assert "scraper" in loaded  # default section
