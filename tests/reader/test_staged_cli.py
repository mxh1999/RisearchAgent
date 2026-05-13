from __future__ import annotations

import pytest

from run import build_parser


def test_read_staged_text_file_args() -> None:
    args = build_parser().parse_args(
        [
            "read",
            "--staged",
            "--text-file",
            "paper.txt",
            "--paper-id",
            "sample",
            "--title",
            "Sample Paper",
            "--output-root",
            "data/readings-test",
        ]
    )

    assert args.command == "read"
    assert args.staged is True
    assert args.text_file == "paper.txt"
    assert args.paper_id == "sample"
    assert args.title == "Sample Paper"


def test_read_staged_rejects_missing_source() -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(
            ["read", "--staged", "--paper-id", "sample", "--title", "Sample Paper"]
        )

    assert exc_info.value.code == 2
