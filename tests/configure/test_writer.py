"""Atomic writer tests."""

from __future__ import annotations

import time
from pathlib import Path

import yaml

from src.configure.writer import write_config_atomically


def test_writes_yaml_to_target(tmp_path: Path):
    target = tmp_path / "config.yaml"
    write_config_atomically(target, {"a": 1, "b": [1, 2]})
    assert target.exists()
    loaded = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert loaded == {"a": 1, "b": [1, 2]}


def test_first_write_does_not_create_backup(tmp_path: Path):
    target = tmp_path / "config.yaml"
    backup = write_config_atomically(target, {"x": 1})
    assert backup is None
    bak_files = list(tmp_path.glob("config.yaml.bak.*"))
    assert bak_files == []


def test_overwrite_creates_timestamped_backup(tmp_path: Path):
    target = tmp_path / "config.yaml"
    write_config_atomically(target, {"v": 1})
    time.sleep(1.1)  # ensure distinct ISO timestamp
    backup = write_config_atomically(target, {"v": 2})
    assert backup is not None
    assert backup.exists()
    # Backup contains the OLD content
    old = yaml.safe_load(backup.read_text(encoding="utf-8"))
    assert old == {"v": 1}
    # Target contains the NEW content
    new = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert new == {"v": 2}


def test_no_tempfile_left_on_disk(tmp_path: Path):
    target = tmp_path / "config.yaml"
    write_config_atomically(target, {"foo": "bar"})
    leftover = list(tmp_path.glob("*.tmp"))
    assert leftover == []


def test_yaml_uses_block_style_and_unicode(tmp_path: Path):
    target = tmp_path / "config.yaml"
    write_config_atomically(
        target, {"chinese": "中文", "list": ["a", "b"]}
    )
    text = target.read_text(encoding="utf-8")
    # Block-style: "chinese: 中文" not "chinese: !!python/str ..."
    assert "中文" in text
    # default_flow_style=False means lists use - block style
    assert "- a" in text
