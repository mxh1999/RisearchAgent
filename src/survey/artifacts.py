from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

import yaml

from src.survey.models import SurveyEvent, TopicProfile


AUTO_BEGIN = "<!-- BEGIN AUTO:{name} -->"
AUTO_END = "<!-- END AUTO:{name} -->"


@dataclass(frozen=True)
class TopicArtifactPaths:
    topic_dir: Path
    topic_yaml: Path


class TopicArtifactManager:
    """Create and update stable artifact files for one survey topic."""

    def __init__(self, topics_root: Path = Path("data/topics")):
        self.topics_root = topics_root

    def create_or_update_topic(self, profile: TopicProfile) -> TopicArtifactPaths:
        self._validate_topic_id(profile.topic_id)
        topic_dir = self.topics_root / profile.topic_id
        state_dir = topic_dir / "state"
        papers_dir = topic_dir / "papers"
        state_dir.mkdir(parents=True, exist_ok=True)
        papers_dir.mkdir(parents=True, exist_ok=True)

        topic_yaml = topic_dir / "topic.yaml"
        topic_yaml.write_text(
            yaml.safe_dump(profile.to_dict(), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

        self._ensure_file(
            topic_dir / "survey.md",
            f"# {profile.name} Survey\n\n"
            f"{AUTO_BEGIN.format(name='taxonomy')}\n"
            "No taxonomy has been generated yet.\n"
            f"{AUTO_END.format(name='taxonomy')}\n",
        )
        self._ensure_file(
            topic_dir / "papers.md",
            f"# {profile.name} Papers\n\n"
            f"{AUTO_BEGIN.format(name='paper-map')}\n"
            "No papers have been classified yet.\n"
            f"{AUTO_END.format(name='paper-map')}\n",
        )
        self._ensure_file(
            topic_dir / "references.md",
            f"# {profile.name} References\n\n"
            f"{AUTO_BEGIN.format(name='references')}\n"
            "No references have been collected yet.\n"
            f"{AUTO_END.format(name='references')}\n",
        )
        self._ensure_file(
            topic_dir / "positioning.md",
            f"# {profile.name} Positioning\n\n"
            f"{AUTO_BEGIN.format(name='positioning')}\n"
            "No positioning analysis has been generated yet.\n"
            f"{AUTO_END.format(name='positioning')}\n",
        )
        self._ensure_file(state_dir / "survey_events.jsonl", "")

        return TopicArtifactPaths(topic_dir=topic_dir, topic_yaml=topic_yaml)

    def update_auto_block(self, path: Path, block_name: str, content: str) -> None:
        begin = AUTO_BEGIN.format(name=block_name)
        end = AUTO_END.format(name=block_name)
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        replacement = f"{begin}\n{content.rstrip()}\n{end}"

        begin_index = text.find(begin)
        if begin_index >= 0:
            end_index = text.find(end, begin_index + len(begin))
        else:
            end_index = -1

        if begin_index >= 0 and end_index >= 0:
            before = text[:begin_index]
            after = text[end_index + len(end) :]
            updated = before + replacement + after
        else:
            updated = text.rstrip() + "\n\n" + replacement + "\n"

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(updated, encoding="utf-8")

    def append_event(self, topic_dir: Path, event: SurveyEvent) -> None:
        event_path = topic_dir / "state" / "survey_events.jsonl"
        event_path.parent.mkdir(parents=True, exist_ok=True)
        with event_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    @staticmethod
    def _ensure_file(path: Path, content: str) -> None:
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    @staticmethod
    def _validate_topic_id(topic_id: str) -> None:
        posix_path = PurePosixPath(topic_id)
        windows_path = PureWindowsPath(topic_id)
        invalid = (
            not topic_id
            or topic_id in {".", ".."}
            or posix_path.is_absolute()
            or windows_path.is_absolute()
            or bool(windows_path.drive)
            or len(posix_path.parts) != 1
            or len(windows_path.parts) != 1
        )
        if invalid:
            raise ValueError(f"Invalid topic_id: {topic_id!r}")
