from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional, Protocol, Sequence

from src.reader.staged_models import (
    Evidence,
    ExperimentRecord,
    MethodModule,
    PageText,
    PaperReadingPackage,
    PaperSummary,
    TopicRelation,
)


STAGES = ("summary", "section_notes", "method", "experiments", "topic_relation")


class StagedReaderLLM(Protocol):
    def generate_json(
        self,
        prompt: str,
        model: Optional[str],
        temperature: Optional[float],
    ) -> Any:
        ...


class StagedPaperReader:
    def __init__(self, llm: StagedReaderLLM, model: Optional[str]) -> None:
        self.llm = llm
        self.model = model

    async def read(
        self,
        paper_id: str,
        title: str,
        source_path: str,
        pages: Sequence[PageText],
        topic_context: str,
    ) -> PaperReadingPackage:
        outputs = {}
        for stage in STAGES:
            outputs[stage] = self._generate(
                stage=stage,
                title=title,
                topic_context=topic_context,
                pages=pages,
            )

        summary = _parse_summary(outputs["summary"])
        claims, critique, follow_up_questions = _parse_section_notes(
            outputs["section_notes"]
        )
        method_modules = _parse_method(outputs["method"])
        experiments = _parse_experiments(outputs["experiments"])
        topic_relation = _parse_topic_relation(outputs["topic_relation"])

        return PaperReadingPackage(
            paper_id=paper_id,
            title=title,
            source_path=source_path,
            pages=list(pages),
            summary=summary,
            claims=claims,
            method_modules=method_modules,
            experiments=experiments,
            topic_relation=topic_relation,
            critique=critique,
            follow_up_questions=follow_up_questions,
        )

    def _generate(
        self,
        stage: str,
        title: str,
        topic_context: str,
        pages: Sequence[PageText],
    ) -> Any:
        prompt = "\n".join(
            [
                f"Stage: {stage}",
                f"Paper title: {title}",
                "Topic context:",
                topic_context,
                "Page-marked text:",
                _format_pages(pages),
            ]
        )
        return self.llm.generate_json(prompt, model=self.model, temperature=0.1)


def _format_pages(pages: Sequence[PageText]) -> str:
    return "\n\n".join(f"[Page {page.page}]\n{page.text}" for page in pages)


def _parse_summary(raw: Any) -> PaperSummary:
    root = _require_mapping(raw, "summary_response")
    summary = _require_mapping(_required(root, "summary", "summary"), "summary")
    _require_string(_required(summary, "problem", "summary.problem"), "summary.problem")
    _require_string(_required(summary, "method", "summary.method"), "summary.method")
    _require_string(
        _required(summary, "takeaway", "summary.takeaway"), "summary.takeaway"
    )
    _require_string_list(summary.get("contributions", []), "summary.contributions")
    return PaperSummary.from_dict(summary)


def _parse_section_notes(raw: Any) -> tuple[list[Evidence], list[str], list[str]]:
    root = _require_mapping(raw, "section_notes_response")
    claims_raw = _require_list(root.get("claims", []), "claims")
    critique = _require_string_list(root.get("critique", []), "critique")
    follow_up_questions = _require_string_list(
        root.get("follow_up_questions", []), "follow_up_questions"
    )

    claims = []
    for index, claim_raw in enumerate(claims_raw):
        claim = _require_mapping(claim_raw, f"claims[{index}]")
        _validate_evidence(claim, f"claims[{index}]")
        claims.append(Evidence.from_dict(claim))
    return claims, critique, follow_up_questions


def _parse_method(raw: Any) -> list[MethodModule]:
    root = _require_mapping(raw, "method_response")
    modules_raw = _require_list(root.get("method_modules", []), "method_modules")
    modules = []
    for index, module_raw in enumerate(modules_raw):
        path = f"method_modules[{index}]"
        module = _require_mapping(module_raw, path)
        _require_string(_required(module, "name", f"{path}.name"), f"{path}.name")
        _require_string(_required(module, "role", f"{path}.role"), f"{path}.role")
        _require_string_list(module.get("inputs", []), f"{path}.inputs")
        _require_string_list(module.get("outputs", []), f"{path}.outputs")
        modules.append(MethodModule.from_dict(module))
    return modules


def _parse_experiments(raw: Any) -> list[ExperimentRecord]:
    root = _require_mapping(raw, "experiments_response")
    records_raw = _require_list(root.get("experiments", []), "experiments")
    records = []
    for index, record_raw in enumerate(records_raw):
        path = f"experiments[{index}]"
        record = _require_mapping(record_raw, path)
        for key in ("benchmark", "setting", "metric", "method"):
            _require_string(_required(record, key, f"{path}.{key}"), f"{path}.{key}")
        _require_number(_required(record, "value", f"{path}.value"), f"{path}.value")
        _require_boolish(
            _required(record, "higher_is_better", f"{path}.higher_is_better"),
            f"{path}.higher_is_better",
        )
        source = _require_mapping(_required(record, "source", f"{path}.source"), f"{path}.source")
        _validate_evidence(source, f"{path}.source")
        records.append(ExperimentRecord.from_dict(record))
    return records


def _parse_topic_relation(raw: Any) -> TopicRelation:
    root = _require_mapping(raw, "topic_relation_response")
    relation = _require_mapping(
        _required(root, "topic_relation", "topic_relation"), "topic_relation"
    )
    _require_string(
        _required(relation, "relevance", "topic_relation.relevance"),
        "topic_relation.relevance",
    )
    _require_string_list(
        relation.get("concept_axes", []), "topic_relation.concept_axes"
    )
    if "collision_risk" in relation:
        _require_string(
            relation["collision_risk"], "topic_relation.collision_risk"
        )
    if "differentiation" in relation:
        _require_string(
            relation["differentiation"], "topic_relation.differentiation"
        )
    return TopicRelation.from_dict(relation)


def _validate_evidence(raw: Mapping[str, Any], path: str) -> None:
    _require_string(_required(raw, "text", f"{path}.text"), f"{path}.text")
    _require_int(_required(raw, "page", f"{path}.page"), f"{path}.page")
    _require_string(_required(raw, "section", f"{path}.section"), f"{path}.section")
    _require_string(_required(raw, "quote", f"{path}.quote"), f"{path}.quote")
    _require_string(
        _required(raw, "confidence", f"{path}.confidence"), f"{path}.confidence"
    )


def _required(raw: Mapping[str, Any], key: str, path: str) -> Any:
    if key not in raw:
        raise ValueError(f"{path} is required")
    return raw[key]


def _require_mapping(raw: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{path} must be an object")
    return raw


def _require_list(raw: Any, path: str) -> list[Any]:
    if not isinstance(raw, list):
        raise ValueError(f"{path} must be a list")
    return raw


def _require_string(raw: Any, path: str) -> str:
    if not isinstance(raw, str):
        raise ValueError(f"{path} must be a string")
    return raw


def _require_string_list(raw: Any, path: str) -> list[str]:
    items = _require_list(raw, path)
    for index, item in enumerate(items):
        _require_string(item, f"{path}[{index}]")
    return items


def _require_int(raw: Any, path: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"{path} must be an integer")
    return raw


def _require_number(raw: Any, path: str) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{path} must be a number")
    return float(raw)


def _require_boolish(raw: Any, path: str) -> Any:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and raw.strip().lower() in {"true", "false"}:
        return raw
    raise ValueError(f"{path} must be a boolean")
