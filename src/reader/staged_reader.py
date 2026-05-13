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
from src.survey.models import TopicProfile


STAGES = ("summary", "section_notes", "method", "experiments", "topic_relation")


class StagedReaderLLM(Protocol):
    async def generate_json(
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
        topic: Optional[TopicProfile] = None,
    ) -> PaperReadingPackage:
        topic_context = _topic_to_prompt_text(topic)
        summary = _parse_summary(
            await self._generate(
                stage="summary",
                title=title,
                topic_context=topic_context,
                pages=pages,
            )
        )
        claims, critique, follow_up_questions = _parse_section_notes(
            await self._generate(
                stage="section_notes",
                title=title,
                topic_context=topic_context,
                pages=pages,
            )
        )
        method_modules = _parse_method(
            await self._generate(
                stage="method",
                title=title,
                topic_context=topic_context,
                pages=pages,
            )
        )
        experiments = _parse_experiments(
            await self._generate(
                stage="experiments",
                title=title,
                topic_context=topic_context,
                pages=pages,
            )
        )
        topic_relation = _parse_topic_relation(
            await self._generate(
                stage="topic_relation",
                title=title,
                topic_context=topic_context,
                pages=pages,
            )
        )

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

    async def _generate(
        self,
        stage: str,
        title: str,
        topic_context: str,
        pages: Sequence[PageText],
    ) -> Any:
        prompt = "\n".join(
            [
                "## Stage",
                stage,
                "",
                "## Paper Title",
                title,
                "",
                "## Topic Context",
                topic_context,
                "",
                "## Output Schema",
                _schema_instructions(stage),
                "",
                "## Paper Text",
                _pages_to_prompt_text(pages),
            ]
        )
        return await self.llm.generate_json(prompt, model=self.model, temperature=0.1)


def _topic_to_prompt_text(topic: Optional[TopicProfile]) -> str:
    if topic is None:
        return "No topic profile provided."

    concept_axes = "\n".join(
        f"- {axis.name}: {axis.description}" for axis in topic.concept_axes
    )
    if not concept_axes:
        concept_axes = "- None"

    return "\n".join(
        [
            f"Topic ID: {topic.topic_id}",
            f"Name: {topic.name}",
            f"Description: {topic.description}",
            f"Intent: {topic.intent}",
            "Concept axes:",
            concept_axes,
            f"Positive scope: {', '.join(topic.scope.positive) or 'None'}",
            f"Negative scope: {', '.join(topic.scope.negative) or 'None'}",
            f"Adjacent scope: {', '.join(topic.scope.adjacent) or 'None'}",
            f"Collision scope: {', '.join(topic.scope.collision) or 'None'}",
            f"Anchor papers: {', '.join(topic.anchor_papers) or 'None'}",
            f"Benchmark hints: {', '.join(topic.benchmark_hints) or 'None'}",
            f"Open questions: {', '.join(topic.open_questions) or 'None'}",
        ]
    )


def _schema_instructions(stage: str) -> str:
    schemas = {
        "summary": (
            "Return JSON with key summary containing string keys problem, method, "
            "takeaway and list[str] contributions."
        ),
        "section_notes": (
            "Return JSON with keys claims, critique, follow_up_questions. claims must "
            "be a list of evidence objects with text, page, section, quote, confidence."
        ),
        "method": (
            "Return JSON with key method_modules: list of objects with name, role, "
            "inputs, outputs."
        ),
        "experiments": (
            "Return JSON with key experiments: list of objects with benchmark, "
            "setting, metric, method, value, higher_is_better, source. Use \"N/A\" "
            "for unknown string fields; do not use null. source must be an object "
            "with text, page, section, quote, confidence. Do not use source_evidence."
        ),
        "topic_relation": (
            "Return JSON with key topic_relation containing relevance, concept_axes, "
            "collision_risk, differentiation. If no topic profile is provided, "
            "return relevance \"unknown\", concept_axes [], collision_risk "
            "\"unknown\", differentiation \"\"."
        ),
    }
    return schemas[stage]


def _pages_to_prompt_text(
    pages: Sequence[PageText],
    max_chars: int = 60000,
) -> str:
    chunks = []
    remaining = max_chars
    for page in pages:
        if remaining <= 0:
            break
        page_text = f"[Page {page.page}]\n{page.text}"
        chunks.append(page_text[:remaining])
        remaining -= len(chunks[-1])
    return "\n\n".join(chunks)


def _parse_summary(raw: Any) -> PaperSummary:
    root = _require_mapping(raw, "summary_response")
    summary = dict(_require_mapping(_required(root, "summary", "summary"), "summary"))
    _require_string(_required(summary, "problem", "summary.problem"), "summary.problem")
    _require_string(_required(summary, "method", "summary.method"), "summary.method")
    _require_string(
        _required(summary, "takeaway", "summary.takeaway"), "summary.takeaway"
    )
    summary["contributions"] = _require_string_list(
        summary.get("contributions", []), "summary.contributions"
    )
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
        module = dict(_require_mapping(module_raw, path))
        _require_string(_required(module, "name", f"{path}.name"), f"{path}.name")
        _require_string(_required(module, "role", f"{path}.role"), f"{path}.role")
        module["inputs"] = _require_string_list(module.get("inputs", []), f"{path}.inputs")
        module["outputs"] = _require_string_list(
            module.get("outputs", []), f"{path}.outputs"
        )
        modules.append(MethodModule.from_dict(module))
    return modules


def _parse_experiments(raw: Any) -> list[ExperimentRecord]:
    root = _require_mapping(raw, "experiments_response")
    records_raw = _require_list(root.get("experiments", []), "experiments")
    records = []
    for index, record_raw in enumerate(records_raw):
        path = f"experiments[{index}]"
        record = dict(_require_mapping(record_raw, path))
        if record.get("setting") is None:
            record["setting"] = "N/A"
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
    relation = dict(
        _require_mapping(
            _required(root, "topic_relation", "topic_relation"),
            "topic_relation",
        )
    )
    if relation.get("relevance") is None:
        relation["relevance"] = "unknown"
    if relation.get("collision_risk") is None:
        relation["collision_risk"] = "unknown"
    if relation.get("differentiation") is None:
        relation["differentiation"] = ""
    _require_string(
        _required(relation, "relevance", "topic_relation.relevance"),
        "topic_relation.relevance",
    )
    relation["concept_axes"] = _require_string_list(
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
    _require_scalar_string(
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


def _require_scalar_string(raw: Any, path: str) -> Any:
    if raw is None or isinstance(raw, (list, Mapping)):
        raise ValueError(f"{path} must be a string-like scalar")
    return raw


def _require_string_list(raw: Any, path: str) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    items = _require_list(raw, path)
    for index, item in enumerate(items):
        _require_string(item, f"{path}[{index}]")
    return items


def _require_int(raw: Any, path: str) -> int:
    if isinstance(raw, bool):
        raise ValueError(f"{path} must be an integer")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        try:
            int(raw)
        except ValueError:
            pass
        else:
            return int(raw)
    raise ValueError(f"{path} must be an integer")


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
