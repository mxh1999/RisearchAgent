from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

import yaml

from src.reader.staged_models import PaperReadingPackage
from src.survey.cli import _load_topic, _validate_topic_path
from src.survey.models import TopicProfile
from src.survey.reading_loader import load_reading_packages

VALID_DECISIONS = {"accept", "reject", "uncertain"}


class RelevanceLLM(Protocol):
    async def generate_json(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        ...


@dataclass(frozen=True)
class RelevanceDecision:
    paper_id: str
    decision: str
    score: float
    reason: str
    matched_topic_aspects: list[str] = field(default_factory=list)
    missing_topic_aspects: list[str] = field(default_factory=list)
    include: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "decision": self.decision,
            "score": self.score,
            "reason": self.reason,
            "matched_topic_aspects": list(self.matched_topic_aspects),
            "missing_topic_aspects": list(self.missing_topic_aspects),
            "include": self.include,
        }


@dataclass(frozen=True)
class ScreeningReport:
    topic_id: str
    candidates_path: Path
    threshold: float
    dry_run: bool
    decisions: list[RelevanceDecision]

    @property
    def accepted(self) -> list[str]:
        return [decision.paper_id for decision in self.decisions if decision.include]

    @property
    def rejected(self) -> list[str]:
        return [decision.paper_id for decision in self.decisions if not decision.include]

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "candidates_path": str(self.candidates_path),
            "threshold": self.threshold,
            "dry_run": self.dry_run,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "decisions": [decision.to_dict() for decision in self.decisions],
        }


@dataclass(frozen=True)
class ValidationReport:
    topic_id: str
    readings_dir: Path
    threshold: float
    dry_run: bool
    decisions: list[RelevanceDecision]

    @property
    def included(self) -> list[str]:
        return [decision.paper_id for decision in self.decisions if decision.include]

    @property
    def excluded(self) -> list[str]:
        return [decision.paper_id for decision in self.decisions if not decision.include]

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "readings_dir": str(self.readings_dir),
            "threshold": self.threshold,
            "dry_run": self.dry_run,
            "included": self.included,
            "excluded": self.excluded,
            "decisions": [decision.to_dict() for decision in self.decisions],
        }


async def screen_discovery_candidates(
    *,
    topic_path: Path,
    candidates_path: Path,
    threshold: float,
    limit: int | None,
    dry_run: bool,
    llm: RelevanceLLM,
    model: str | None,
) -> ScreeningReport:
    _validate_threshold(threshold)
    topic = _load_topic(topic_path)
    topic_dir = topic_path.parent
    _validate_topic_path(topic, topic_dir)
    raw = _load_candidates_json(candidates_path, topic.topic_id)
    candidates = raw["candidates"]
    decisions: list[RelevanceDecision] = []

    for candidate in _limited(candidates, limit):
        if not isinstance(candidate, dict):
            continue
        if candidate.get("status", "candidate") not in {"candidate", "rejected", "uncertain"}:
            continue
        decision = await _screen_candidate(topic, candidate, threshold, llm, model)
        decisions.append(decision)
        candidate["relevance"] = _relevance_payload(decision)
        candidate["status"] = "candidate" if decision.include else "rejected"

    report = ScreeningReport(
        topic_id=topic.topic_id,
        candidates_path=candidates_path,
        threshold=threshold,
        dry_run=dry_run,
        decisions=decisions,
    )
    _write_json(topic_dir / "state" / "screening_report.json", report.to_dict())

    if not dry_run:
        _write_json(candidates_path, raw)
        _write_discovery_markdown(topic_dir / "discovery.md", topic, raw)
        _write_screened_manifest_draft(topic_dir / "ingest_manifest.draft.yaml", raw)

    return report


async def validate_reading_packages(
    *,
    topic_path: Path,
    readings_dir: Path | None,
    threshold: float,
    limit: int | None,
    dry_run: bool,
    llm: RelevanceLLM,
    model: str | None,
) -> ValidationReport:
    _validate_threshold(threshold)
    topic = _load_topic(topic_path)
    topic_dir = topic_path.parent
    _validate_topic_path(topic, topic_dir)
    resolved_readings_dir = readings_dir if readings_dir is not None else topic_dir / "papers"
    packages = load_reading_packages(resolved_readings_dir)

    decisions: list[RelevanceDecision] = []
    for package in _limited(packages, limit):
        decisions.append(await _validate_package(topic, package, threshold, llm, model))
    decisions = sorted(decisions, key=lambda decision: decision.paper_id)

    report = ValidationReport(
        topic_id=topic.topic_id,
        readings_dir=resolved_readings_dir,
        threshold=threshold,
        dry_run=dry_run,
        decisions=decisions,
    )
    report_name = (
        "relevance_validations.dry_run.json"
        if dry_run
        else "relevance_validations.json"
    )
    _write_json(topic_dir / "state" / report_name, report.to_dict())
    return report


def load_validation_inclusions(topic_dir: Path) -> dict[str, bool]:
    path = topic_dir / "state" / "relevance_validations.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid relevance validations JSON: {path}") from exc
    if not isinstance(raw, dict):
        raise ValueError("Relevance validations must be a mapping")
    decisions = raw.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError("Relevance validations must contain decisions")
    inclusions: dict[str, bool] = {}
    for index, item in enumerate(decisions):
        if not isinstance(item, dict):
            raise ValueError(f"Validation decision at index {index} must be a mapping")
        paper_id = item.get("paper_id")
        include = item.get("include")
        if not isinstance(paper_id, str) or not isinstance(include, bool):
            raise ValueError(f"Validation decision at index {index} is malformed")
        inclusions[paper_id] = include
    return inclusions


async def _screen_candidate(
    topic: TopicProfile,
    candidate: dict[str, Any],
    threshold: float,
    llm: RelevanceLLM,
    model: str | None,
) -> RelevanceDecision:
    paper_id = str(candidate.get("paper_id", ""))
    prompt = _build_screen_prompt(topic, candidate)
    try:
        raw = await llm.generate_json(prompt, model=model, temperature=0.0)
        return _parse_decision(raw, paper_id, threshold)
    except Exception as exc:
        return RelevanceDecision(
            paper_id=paper_id,
            decision="uncertain",
            score=threshold,
            reason=f"Screening failed: {exc}",
            include=True,
        )


async def _validate_package(
    topic: TopicProfile,
    package: PaperReadingPackage,
    threshold: float,
    llm: RelevanceLLM,
    model: str | None,
) -> RelevanceDecision:
    prompt = _build_validation_prompt(topic, package)
    try:
        raw = await llm.generate_json(prompt, model=model, temperature=0.0)
        return _parse_decision(raw, package.paper_id, threshold)
    except Exception as exc:
        return RelevanceDecision(
            paper_id=package.paper_id,
            decision="uncertain",
            score=threshold,
            reason=f"Validation failed: {exc}",
            include=True,
        )


def _parse_decision(raw: Any, paper_id: str, threshold: float) -> RelevanceDecision:
    if not isinstance(raw, dict):
        raise ValueError("Relevance response must be a JSON object")
    decision = str(raw.get("decision", "")).strip().lower()
    if decision not in VALID_DECISIONS:
        raise ValueError(f"Invalid relevance decision: {decision!r}")
    score = float(raw.get("score", 0.0))
    if score < 0.0 or score > 1.0:
        raise ValueError("Relevance score must be in [0, 1]")
    include = decision == "uncertain" or (decision == "accept" and score >= threshold)
    return RelevanceDecision(
        paper_id=paper_id,
        decision=decision,
        score=score,
        reason=str(raw.get("reason", "")).strip(),
        matched_topic_aspects=_string_list(raw.get("matched_topic_aspects", [])),
        missing_topic_aspects=_string_list(raw.get("missing_topic_aspects", [])),
        include=include,
    )


def _build_screen_prompt(topic: TopicProfile, candidate: dict[str, Any]) -> str:
    payload = {
        "topic": topic.to_dict(),
        "candidate": {
            "paper_id": candidate.get("paper_id"),
            "title": candidate.get("title"),
            "abstract": candidate.get("abstract"),
            "categories": candidate.get("categories"),
            "matched_queries": candidate.get("matched_queries"),
            "query_rationales": candidate.get("query_rationales"),
            "source_url": candidate.get("source_url"),
        },
    }
    return _prompt(
        "Decide whether this discovered paper belongs in the topic reading queue.",
        payload,
    )


def _build_validation_prompt(topic: TopicProfile, package: PaperReadingPackage) -> str:
    payload = {
        "topic": topic.to_dict(),
        "reading_package": {
            "paper_id": package.paper_id,
            "title": package.title,
            "summary": package.summary.to_dict() if package.summary else None,
            "method_modules": [module.to_dict() for module in package.method_modules[:8]],
            "claims": [claim.to_dict() for claim in package.claims[:8]],
            "experiments": [record.to_dict() for record in package.experiments[:8]],
            "topic_relation": (
                package.topic_relation.to_dict() if package.topic_relation else None
            ),
            "critique": package.critique[:8],
            "follow_up_questions": package.follow_up_questions[:8],
        },
    }
    return _prompt(
        "Decide whether this fully read paper should be included in topic survey and SOTA artifacts.",
        payload,
    )


def _prompt(instruction: str, payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            instruction,
            "Use the topic scope as the authority. Reject lexical false positives.",
            "Return one JSON object with keys: decision, score, reason, matched_topic_aspects, missing_topic_aspects.",
            "decision must be one of: accept, reject, uncertain. score must be between 0 and 1.",
            "",
            json.dumps(payload, ensure_ascii=False, indent=2),
        ]
    )


def _load_candidates_json(candidates_path: Path, topic_id: str) -> dict[str, Any]:
    try:
        raw = json.loads(candidates_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Error loading discovery candidates {candidates_path}: not found") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid discovery candidates JSON: {candidates_path}") from exc
    if not isinstance(raw, dict):
        raise ValueError("Discovery candidates must be a mapping")
    if raw.get("topic_id") != topic_id:
        raise ValueError("Discovery candidates topic_id does not match topic YAML")
    if not isinstance(raw.get("candidates"), list):
        raise ValueError("Discovery candidates must contain a candidates list")
    return raw


def _write_discovery_markdown(
    path: Path,
    topic: TopicProfile,
    raw: dict[str, Any],
) -> None:
    lines = [
        f"# Discovery Candidates: {topic.name}",
        "",
        "## Summary",
        "",
        f"- Topic ID: `{topic.topic_id}`",
        f"- Candidate Count: {len(raw.get('candidates', []))}",
        "",
        "## Candidates",
        "",
        "| Paper ID | Status | Score | Decision | Title | Reason |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for candidate in raw.get("candidates", []):
        relevance = candidate.get("relevance") if isinstance(candidate, dict) else None
        relevance = relevance if isinstance(relevance, dict) else {}
        lines.append(
            "| "
            + " | ".join(
                [
                    _markdown_cell(candidate.get("paper_id", "")),
                    _markdown_cell(candidate.get("status", "")),
                    _markdown_cell(relevance.get("score", "")),
                    _markdown_cell(relevance.get("decision", "")),
                    _markdown_cell(candidate.get("title", "")),
                    _markdown_cell(relevance.get("reason", "")),
                ]
            )
            + " |"
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_screened_manifest_draft(path: Path, raw: dict[str, Any]) -> None:
    papers = []
    for candidate in raw.get("candidates", []):
        if not isinstance(candidate, dict) or candidate.get("status") != "candidate":
            continue
        papers.append(
            {
                "paper_id": candidate["paper_id"],
                "title": candidate["title"],
                "pdf_url": candidate["pdf_url"],
                "source_url": candidate["source_url"],
                "venue": "arXiv",
                "year": candidate.get("year"),
            }
        )
    path.write_text(
        yaml.safe_dump({"papers": papers}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _relevance_payload(decision: RelevanceDecision) -> dict[str, Any]:
    raw = decision.to_dict()
    raw.pop("paper_id", None)
    raw.pop("include", None)
    return raw


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _validate_threshold(threshold: float) -> None:
    if threshold <= 0.0 or threshold > 1.0:
        raise ValueError("threshold must be in (0, 1]")


def _limited(values, limit: int | None):
    if limit is None:
        return list(values)
    if limit < 1:
        raise ValueError("limit must be >= 1")
    return list(values)[:limit]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _markdown_cell(value: object) -> str:
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\n", "<br>").replace("|", r"\|")
