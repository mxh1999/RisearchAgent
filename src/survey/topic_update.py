from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src.reader.staged_models import PaperReadingPackage
from src.survey.models import TopicProfile


@dataclass
class TopicUpdateStepReport:
    status: str
    artifacts: list[str] = field(default_factory=list)
    record_count: int = 0
    setting_group_count: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TopicUpdateReport:
    topic_id: str
    topic_name: str
    readings_dir: str
    paper_count: int
    paper_ids: list[str]
    papers_with_experiments: list[str]
    papers_without_experiments: list[str]
    survey: TopicUpdateStepReport = field(
        default_factory=lambda: TopicUpdateStepReport(status="pending")
    )
    sota: TopicUpdateStepReport = field(
        default_factory=lambda: TopicUpdateStepReport(status="pending")
    )
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "topic_name": self.topic_name,
            "readings_dir": self.readings_dir,
            "paper_count": self.paper_count,
            "paper_ids": list(self.paper_ids),
            "papers_with_experiments": list(self.papers_with_experiments),
            "papers_without_experiments": list(self.papers_without_experiments),
            "survey": self.survey.to_dict(),
            "sota": self.sota.to_dict(),
            "warnings": list(self.warnings),
        }


def validate_topic_update_options(skip_survey: bool, skip_sota: bool) -> None:
    if skip_survey and skip_sota:
        raise ValueError("topic update cannot skip both survey and SOTA")


def build_preflight_report(
    topic: TopicProfile,
    readings_dir: Path,
    packages: list[PaperReadingPackage],
) -> TopicUpdateReport:
    paper_ids = [package.paper_id for package in packages]
    papers_with_experiments = [
        package.paper_id for package in packages if package.experiments
    ]
    papers_without_experiments = [
        package.paper_id for package in packages if not package.experiments
    ]
    warnings = []
    if papers_without_experiments:
        paper_list = ", ".join(papers_without_experiments)
        count = len(papers_without_experiments)
        suffix = "paper has" if count == 1 else "papers have"
        warnings.append(
            f"{count} {suffix} no experiment records: {paper_list}"
        )
    return TopicUpdateReport(
        topic_id=topic.topic_id,
        topic_name=topic.name,
        readings_dir=str(readings_dir),
        paper_count=len(packages),
        paper_ids=paper_ids,
        papers_with_experiments=papers_with_experiments,
        papers_without_experiments=papers_without_experiments,
        warnings=warnings,
    )


def write_topic_update_report(topic_dir: Path, report: TopicUpdateReport) -> Path:
    report_path = topic_dir / "state" / "topic_update_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return report_path
