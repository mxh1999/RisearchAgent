from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src.reader.staged_models import PaperReadingPackage
from src.survey.cli import _load_topic, _validate_topic_path, synthesize_survey_artifacts
from src.survey.models import TopicProfile
from src.survey.reading_loader import load_reading_packages
from src.survey.sota_cli import _load_registry, update_sota_artifacts
from src.survey.synthesizer import SurveySynthesizer


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


async def update_topic_artifacts(
    topic_path: Path,
    readings_dir: Path | None,
    survey_llm,
    survey_model: str | None,
    sota_llm,
    sota_model: str | None,
    skip_survey: bool,
    skip_sota: bool,
    use_sota_llm: bool,
) -> TopicUpdateReport:
    validate_topic_update_options(skip_survey=skip_survey, skip_sota=skip_sota)
    topic = _load_topic(topic_path)
    topic_dir = topic_path.parent
    _validate_topic_path(topic, topic_dir)
    source_dir = readings_dir if readings_dir is not None else topic_dir / "papers"

    try:
        packages = load_reading_packages(source_dir)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(f"Error loading reading packages: {exc}") from exc

    report = build_preflight_report(topic, source_dir, packages)

    if skip_survey:
        report.survey = TopicUpdateStepReport(status="skipped")
    else:
        if survey_llm is None:
            raise ValueError("survey_llm is required when survey update is enabled")
        try:
            synthesis = await SurveySynthesizer(
                survey_llm, model=survey_model
            ).synthesize(topic, packages)
        except ValueError as exc:
            raise SystemExit(f"Error synthesizing survey: {exc}") from exc
        survey_paths = await synthesize_survey_artifacts(
            topic=topic,
            topic_dir=topic_dir,
            packages=packages,
            synthesis=synthesis,
        )
        report.survey = TopicUpdateStepReport(
            status="updated",
            artifacts=[str(path.relative_to(topic_dir)) for path in survey_paths.values()],
        )

    if skip_sota:
        report.sota = TopicUpdateStepReport(status="skipped")
    else:
        registry = _load_registry(topic_dir / "state" / "sota_setting_groups.json")
        try:
            sota_result = await update_sota_artifacts(
                topic=topic,
                topic_dir=topic_dir,
                packages=packages,
                registry=registry,
                llm=sota_llm,
                model=sota_model,
                use_llm=use_sota_llm,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        report.sota = TopicUpdateStepReport(
            status="updated",
            artifacts=[
                str(sota_result["sota"].relative_to(topic_dir)),
                str(sota_result["records"].relative_to(topic_dir)),
                str(sota_result["setting_groups"].relative_to(topic_dir)),
            ],
            record_count=int(sota_result["record_count"]),
            setting_group_count=int(sota_result["setting_group_count"]),
        )

    write_topic_update_report(topic_dir, report)
    return report
