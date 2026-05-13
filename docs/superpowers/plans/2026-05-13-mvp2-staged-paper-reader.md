# MVP-2 Staged PaperReader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a staged, evidence-backed paper reader that produces reusable Markdown and JSON reading packages for one paper.

**Architecture:** Add a new staged reader beside the existing `DeepReader` instead of replacing the current pipeline. The new path uses page-aware text, independent stage schemas, LLM JSON validation, topic-aware critique, and deterministic artifact rendering under a topic directory or output root.

**Tech Stack:** Python dataclasses, PyYAML, JSON, PyMuPDF with lazy import, existing `GeminiClient`, argparse, pytest with fake LLM tests.

---

## Scope

This plan implements MVP-2 only:

- page-aware text extraction for local PDFs;
- a staged reading package data model;
- LLM-backed stages for summary, section notes, claims, method breakdown, experiments, topic relation, and critique;
- Markdown and JSON rendering for one paper;
- CLI support for staged reading from a local PDF or text file;
- tests using fake LLMs and temporary files.

This plan intentionally does not implement:

- arXiv paper collection for staged reading;
- automatic survey synthesis over multiple papers;
- structured SOTA storage;
- replacement of the existing async pipeline `DeepReader`.

The old `python run.py read 2401.12345` behavior must continue to work.

## File Structure

- Create `src/reader/staged_models.py`: dataclasses for page text, evidence, claims, method modules, experiment records, topic relation, critique, and full reading package.
- Create `src/reader/page_extractor.py`: page-aware extraction from local PDF and plain text files with lazy PyMuPDF import.
- Create `src/reader/staged_reader.py`: staged LLM reader with schema validation and fake-LLM-friendly protocol.
- Create `src/reader/reading_renderer.py`: deterministic JSON and Markdown rendering.
- Create `src/reader/staged_cli.py`: command handler for staged local file reading.
- Modify `run.py`: extend `read` parser with staged local options while preserving the existing arXiv-id path.
- Create `tests/reader/test_staged_models.py`: model serialization tests.
- Create `tests/reader/test_page_extractor.py`: local text and mocked PDF extraction tests.
- Create `tests/reader/test_staged_reader.py`: fake LLM stage orchestration and schema validation tests.
- Create `tests/reader/test_reading_renderer.py`: JSON and Markdown artifact tests.
- Create `tests/reader/test_staged_cli.py`: parser and CLI routing tests.

## CLI Target

Existing behavior remains:

```bash
python run.py read 2401.12345
```

New staged local reading behavior:

```bash
python run.py read --staged --pdf paper/MSGNav.pdf --paper-id MSGNav --title "MSGNav" --topic data/topics/task_driven_3d_utility_learning_for_embodied_navigation/topic.yaml
python run.py read --staged --text-file tests/fixtures/sample_paper.txt --paper-id sample_paper --title "Sample Paper" --output-root data/readings-smoke
```

Output with `--topic`:

```text
data/topics/task_driven_3d_utility_learning_for_embodied_navigation/papers/sample_paper.json
data/topics/task_driven_3d_utility_learning_for_embodied_navigation/papers/sample_paper.reading.md
```

Output without `--topic`:

```text
data/readings/sample_paper.json
data/readings/sample_paper.reading.md
```

## Task 1: Staged Reading Data Models

**Files:**
- Create: `src/reader/staged_models.py`
- Test: `tests/reader/test_staged_models.py`

- [ ] **Step 1: Write failing model tests**

Create `tests/reader/test_staged_models.py`:

```python
from __future__ import annotations

from src.reader.staged_models import (
    Evidence,
    ExperimentRecord,
    MethodModule,
    PaperReadingPackage,
    PageText,
    PaperSummary,
    TopicRelation,
)


def test_page_text_to_dict_round_trip() -> None:
    page = PageText(page=1, text="Abstract text", char_start=0, char_end=13)

    restored = PageText.from_dict(page.to_dict())

    assert restored == page


def test_reading_package_round_trip() -> None:
    package = PaperReadingPackage(
        paper_id="sample_paper",
        title="Sample Paper",
        source_path="paper/sample.pdf",
        pages=[PageText(page=1, text="Introduction text", char_start=0, char_end=17)],
        summary=PaperSummary(
            problem="The paper studies navigation decisions.",
            method="It scores candidate viewpoints.",
            takeaway="The key idea is learned utility over memory.",
            contributions=["Task-conditioned utility scoring"],
        ),
        claims=[
            Evidence(
                text="The method improves SPL.",
                page=7,
                section="Experiments",
                quote="Our method improves SPL by 5 points.",
                confidence="high",
            )
        ],
        method_modules=[
            MethodModule(
                name="Utility Head",
                role="Scores object and frontier candidates.",
                inputs=["3D memory", "goal embedding"],
                outputs=["candidate utility"],
            )
        ],
        experiments=[
            ExperimentRecord(
                benchmark="GOAT-Bench",
                setting="val unseen",
                metric="SPL",
                method="SampleNav",
                value=35.1,
                higher_is_better=True,
                source=Evidence(
                    text="SPL result",
                    page=8,
                    section="Experiments",
                    quote="SampleNav obtains 35.1 SPL.",
                    confidence="high",
                ),
            )
        ],
        topic_relation=TopicRelation(
            relevance="core",
            concept_axes=["task_conditioned_utility"],
            collision_risk="medium",
            differentiation="Uses explicit utility rather than prompted reasoning.",
        ),
        critique=["Needs stronger baseline comparisons."],
        follow_up_questions=["How is utility supervised?"],
    )

    restored = PaperReadingPackage.from_dict(package.to_dict())

    assert restored == package
    assert restored.experiments[0].source.page == 8
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest tests/reader/test_staged_models.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'src.reader.staged_models'
```

- [ ] **Step 3: Implement staged models**

Create `src/reader/staged_models.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class PageText:
    page: int
    text: str
    char_start: int
    char_end: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PageText":
        return cls(
            page=int(raw["page"]),
            text=str(raw["text"]),
            char_start=int(raw["char_start"]),
            char_end=int(raw["char_end"]),
        )


@dataclass(frozen=True)
class Evidence:
    text: str
    page: int
    section: str
    quote: str
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Evidence":
        return cls(
            text=str(raw["text"]),
            page=int(raw["page"]),
            section=str(raw["section"]),
            quote=str(raw["quote"]),
            confidence=str(raw["confidence"]),
        )


@dataclass(frozen=True)
class PaperSummary:
    problem: str
    method: str
    takeaway: str
    contributions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PaperSummary":
        return cls(
            problem=str(raw["problem"]),
            method=str(raw["method"]),
            takeaway=str(raw["takeaway"]),
            contributions=[str(item) for item in raw.get("contributions", [])],
        )


@dataclass(frozen=True)
class MethodModule:
    name: str
    role: str
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "MethodModule":
        return cls(
            name=str(raw["name"]),
            role=str(raw["role"]),
            inputs=[str(item) for item in raw.get("inputs", [])],
            outputs=[str(item) for item in raw.get("outputs", [])],
        )


@dataclass(frozen=True)
class ExperimentRecord:
    benchmark: str
    setting: str
    metric: str
    method: str
    value: float
    higher_is_better: bool
    source: Evidence

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["source"] = self.source.to_dict()
        return raw

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ExperimentRecord":
        return cls(
            benchmark=str(raw["benchmark"]),
            setting=str(raw["setting"]),
            metric=str(raw["metric"]),
            method=str(raw["method"]),
            value=float(raw["value"]),
            higher_is_better=bool(raw["higher_is_better"]),
            source=Evidence.from_dict(raw["source"]),
        )


@dataclass(frozen=True)
class TopicRelation:
    relevance: str
    concept_axes: list[str] = field(default_factory=list)
    collision_risk: str = "unknown"
    differentiation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TopicRelation":
        return cls(
            relevance=str(raw["relevance"]),
            concept_axes=[str(item) for item in raw.get("concept_axes", [])],
            collision_risk=str(raw.get("collision_risk", "unknown")),
            differentiation=str(raw.get("differentiation", "")),
        )


@dataclass(frozen=True)
class PaperReadingPackage:
    paper_id: str
    title: str
    source_path: str
    pages: list[PageText] = field(default_factory=list)
    summary: PaperSummary | None = None
    claims: list[Evidence] = field(default_factory=list)
    method_modules: list[MethodModule] = field(default_factory=list)
    experiments: list[ExperimentRecord] = field(default_factory=list)
    topic_relation: TopicRelation | None = None
    critique: list[str] = field(default_factory=list)
    follow_up_questions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "source_path": self.source_path,
            "pages": [page.to_dict() for page in self.pages],
            "summary": self.summary.to_dict() if self.summary else None,
            "claims": [claim.to_dict() for claim in self.claims],
            "method_modules": [module.to_dict() for module in self.method_modules],
            "experiments": [record.to_dict() for record in self.experiments],
            "topic_relation": self.topic_relation.to_dict() if self.topic_relation else None,
            "critique": list(self.critique),
            "follow_up_questions": list(self.follow_up_questions),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PaperReadingPackage":
        summary_raw = raw.get("summary")
        relation_raw = raw.get("topic_relation")
        return cls(
            paper_id=str(raw["paper_id"]),
            title=str(raw["title"]),
            source_path=str(raw["source_path"]),
            pages=[PageText.from_dict(item) for item in raw.get("pages", [])],
            summary=PaperSummary.from_dict(summary_raw) if summary_raw else None,
            claims=[Evidence.from_dict(item) for item in raw.get("claims", [])],
            method_modules=[
                MethodModule.from_dict(item)
                for item in raw.get("method_modules", [])
            ],
            experiments=[
                ExperimentRecord.from_dict(item)
                for item in raw.get("experiments", [])
            ],
            topic_relation=TopicRelation.from_dict(relation_raw) if relation_raw else None,
            critique=[str(item) for item in raw.get("critique", [])],
            follow_up_questions=[
                str(item) for item in raw.get("follow_up_questions", [])
            ],
        )
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
python -m pytest tests/reader/test_staged_models.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit**

```bash
git add src/reader/staged_models.py tests/reader/test_staged_models.py
git commit -m "feat: add staged reading models"
```

## Task 2: Page-Aware Text Extraction

**Files:**
- Create: `src/reader/page_extractor.py`
- Test: `tests/reader/test_page_extractor.py`

- [ ] **Step 1: Write failing page extractor tests**

Create `tests/reader/test_page_extractor.py`:

```python
from __future__ import annotations

import types

from src.reader.page_extractor import extract_pages_from_pdf, extract_pages_from_text_file


def test_extract_pages_from_text_file(tmp_path) -> None:
    text_path = tmp_path / "sample.txt"
    text_path.write_text("Page one text\n\nPage two text", encoding="utf-8")

    pages = extract_pages_from_text_file(text_path)

    assert len(pages) == 1
    assert pages[0].page == 1
    assert pages[0].char_start == 0
    assert pages[0].char_end == len("Page one text\n\nPage two text")
    assert "Page two text" in pages[0].text


def test_extract_pages_from_pdf_uses_lazy_fitz(monkeypatch, tmp_path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF sample")

    class FakePage:
        def __init__(self, text: str):
            self._text = text

        def get_text(self) -> str:
            return self._text

    class FakeDoc:
        def __init__(self):
            self.pages = [FakePage("First page"), FakePage("Second page")]
            self.closed = False

        def __len__(self) -> int:
            return len(self.pages)

        def __getitem__(self, index: int) -> FakePage:
            return self.pages[index]

        def close(self) -> None:
            self.closed = True

    fake_doc = FakeDoc()
    fake_fitz = types.SimpleNamespace(open=lambda path: fake_doc)
    monkeypatch.setitem(__import__("sys").modules, "fitz", fake_fitz)

    pages = extract_pages_from_pdf(pdf_path, max_pages=5)

    assert [page.page for page in pages] == [1, 2]
    assert pages[0].text == "First page"
    assert pages[1].char_start == len("First page\n")
    assert fake_doc.closed is True
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest tests/reader/test_page_extractor.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'src.reader.page_extractor'
```

- [ ] **Step 3: Implement page extractor**

Create `src/reader/page_extractor.py`:

```python
from __future__ import annotations

from pathlib import Path

from src.reader.staged_models import PageText


def extract_pages_from_text_file(path: Path) -> list[PageText]:
    text = path.read_text(encoding="utf-8")
    return [PageText(page=1, text=text, char_start=0, char_end=len(text))]


def extract_pages_from_pdf(path: Path, max_pages: int | None = None) -> list[PageText]:
    try:
        import fitz
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PyMuPDF is required to read PDF files. Run pip install -r requirements.txt."
        ) from exc

    doc = fitz.open(path)
    pages: list[PageText] = []
    char_offset = 0
    try:
        page_count = len(doc)
        limit = page_count if max_pages is None else min(page_count, max_pages)
        for index in range(limit):
            text = doc[index].get_text()
            page = PageText(
                page=index + 1,
                text=text,
                char_start=char_offset,
                char_end=char_offset + len(text),
            )
            pages.append(page)
            char_offset = page.char_end + 1
    finally:
        doc.close()
    return pages
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
python -m pytest tests/reader/test_page_extractor.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit**

```bash
git add src/reader/page_extractor.py tests/reader/test_page_extractor.py
git commit -m "feat: add page-aware extraction"
```

## Task 3: Staged Reader With Schema Validation

**Files:**
- Create: `src/reader/staged_reader.py`
- Test: `tests/reader/test_staged_reader.py`

- [ ] **Step 1: Write failing staged reader tests**

Create `tests/reader/test_staged_reader.py`:

```python
from __future__ import annotations

from typing import Any

import pytest

from src.reader.staged_models import PageText
from src.reader.staged_reader import StagedPaperReader
from src.survey.models import ConceptAxis, TopicProfile, TopicScope


class FakeLLM:
    def __init__(self):
        self.prompts: list[str] = []

    async def generate_json(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float | None = None,
    ) -> Any:
        self.prompts.append(prompt)
        if "Stage: summary" in prompt:
            return {
                "problem": "The paper studies navigation decisions.",
                "method": "It scores candidate viewpoints.",
                "takeaway": "The key idea is learned utility over memory.",
                "contributions": ["Task-conditioned utility scoring"],
            }
        if "Stage: section_notes" in prompt:
            return {
                "claims": [
                    {
                        "text": "The method improves SPL.",
                        "page": 2,
                        "section": "Experiments",
                        "quote": "The method improves SPL.",
                        "confidence": "high",
                    }
                ]
            }
        if "Stage: method" in prompt:
            return {
                "modules": [
                    {
                        "name": "Utility Head",
                        "role": "Scores candidates.",
                        "inputs": ["3D memory"],
                        "outputs": ["utility"],
                    }
                ]
            }
        if "Stage: experiments" in prompt:
            return {
                "experiments": [
                    {
                        "benchmark": "GOAT-Bench",
                        "setting": "val unseen",
                        "metric": "SPL",
                        "method": "SampleNav",
                        "value": 35.1,
                        "higher_is_better": True,
                        "source": {
                            "text": "SPL result",
                            "page": 2,
                            "section": "Experiments",
                            "quote": "SampleNav obtains 35.1 SPL.",
                            "confidence": "high",
                        },
                    }
                ]
            }
        if "Stage: topic_relation" in prompt:
            return {
                "relevance": "core",
                "concept_axes": ["task_conditioned_utility"],
                "collision_risk": "medium",
                "differentiation": "Explicit utility scoring.",
                "critique": ["Needs stronger baselines."],
                "follow_up_questions": ["How is utility supervised?"],
            }
        raise AssertionError(f"Unexpected prompt: {prompt}")


def make_topic() -> TopicProfile:
    return TopicProfile(
        topic_id="task_driven_3d_nav",
        name="Task-Driven 3D Navigation",
        description="Study task-driven 3D utility.",
        intent="Find papers about utility learning.",
        concept_axes=[
            ConceptAxis(
                name="task_conditioned_utility",
                description="Scores navigation candidates.",
            )
        ],
        scope=TopicScope(positive=["3D utility learning"]),
    )


@pytest.mark.asyncio
async def test_staged_reader_builds_package() -> None:
    llm = FakeLLM()
    reader = StagedPaperReader(llm=llm, model="gemini-2.5-pro")
    pages = [
        PageText(page=1, text="Introduction text", char_start=0, char_end=17),
        PageText(page=2, text="Experiments text", char_start=18, char_end=34),
    ]

    package = await reader.read(
        paper_id="sample_paper",
        title="Sample Paper",
        source_path="sample.txt",
        pages=pages,
        topic=make_topic(),
    )

    assert package.summary is not None
    assert package.summary.takeaway == "The key idea is learned utility over memory."
    assert package.claims[0].page == 2
    assert package.method_modules[0].name == "Utility Head"
    assert package.experiments[0].value == 35.1
    assert package.topic_relation is not None
    assert package.topic_relation.relevance == "core"
    assert package.critique == ["Needs stronger baselines."]
    assert len(llm.prompts) == 5


@pytest.mark.asyncio
async def test_staged_reader_rejects_malformed_summary() -> None:
    class BadLLM(FakeLLM):
        async def generate_json(
            self,
            prompt: str,
            *,
            model: str | None = None,
            temperature: float | None = None,
        ) -> Any:
            if "Stage: summary" in prompt:
                return {"problem": ["not a string"]}
            return await super().generate_json(
                prompt, model=model, temperature=temperature
            )

    reader = StagedPaperReader(llm=BadLLM(), model="gemini-2.5-pro")

    with pytest.raises(ValueError, match="summary.problem must be a string"):
        await reader.read(
            paper_id="sample_paper",
            title="Sample Paper",
            source_path="sample.txt",
            pages=[PageText(page=1, text="Text", char_start=0, char_end=4)],
            topic=None,
        )
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest tests/reader/test_staged_reader.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'src.reader.staged_reader'
```

- [ ] **Step 3: Implement staged reader**

Create `src/reader/staged_reader.py`:

```python
from __future__ import annotations

from typing import Any, Protocol

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


class StagedReaderLLM(Protocol):
    async def generate_json(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float | None = None,
    ) -> Any:
        pass


class StagedPaperReader:
    def __init__(self, llm: StagedReaderLLM, model: str):
        self.llm = llm
        self.model = model

    async def read(
        self,
        *,
        paper_id: str,
        title: str,
        source_path: str,
        pages: list[PageText],
        topic: TopicProfile | None = None,
    ) -> PaperReadingPackage:
        text = _pages_to_prompt_text(pages)
        topic_text = _topic_to_prompt_text(topic)

        summary = self._parse_summary(
            await self._generate("summary", title, text, topic_text)
        )
        section_notes = await self._generate("section_notes", title, text, topic_text)
        claims = self._parse_claims(section_notes)
        method_raw = await self._generate("method", title, text, topic_text)
        modules = self._parse_method_modules(method_raw)
        experiment_raw = await self._generate("experiments", title, text, topic_text)
        experiments = self._parse_experiments(experiment_raw)
        relation_raw = await self._generate("topic_relation", title, text, topic_text)
        relation, critique, follow_ups = self._parse_topic_relation(relation_raw)

        return PaperReadingPackage(
            paper_id=paper_id,
            title=title,
            source_path=source_path,
            pages=pages,
            summary=summary,
            claims=claims,
            method_modules=modules,
            experiments=experiments,
            topic_relation=relation,
            critique=critique,
            follow_up_questions=follow_ups,
        )

    async def _generate(
        self,
        stage: str,
        title: str,
        text: str,
        topic_text: str,
    ) -> Any:
        prompt = (
            f"Stage: {stage}\n"
            f"Paper title: {title}\n\n"
            f"Topic context:\n{topic_text}\n\n"
            f"Paper text with page markers:\n{text}\n"
        )
        return await self.llm.generate_json(
            prompt,
            model=self.model,
            temperature=0.1,
        )

    def _parse_summary(self, raw: Any) -> PaperSummary:
        data = _require_mapping(raw, "summary")
        return PaperSummary(
            problem=_require_string(data, "problem", "summary.problem"),
            method=_require_string(data, "method", "summary.method"),
            takeaway=_require_string(data, "takeaway", "summary.takeaway"),
            contributions=_require_string_list(
                data.get("contributions", []),
                "summary.contributions",
            ),
        )

    def _parse_claims(self, raw: Any) -> list[Evidence]:
        data = _require_mapping(raw, "section_notes")
        return [
            _parse_evidence(item, "section_notes.claims")
            for item in _require_list(data.get("claims", []), "section_notes.claims")
        ]

    def _parse_method_modules(self, raw: Any) -> list[MethodModule]:
        data = _require_mapping(raw, "method")
        modules = []
        for item in _require_list(data.get("modules", []), "method.modules"):
            module = _require_mapping(item, "method.modules item")
            modules.append(
                MethodModule(
                    name=_require_string(module, "name", "method.modules.name"),
                    role=_require_string(module, "role", "method.modules.role"),
                    inputs=_require_string_list(
                        module.get("inputs", []),
                        "method.modules.inputs",
                    ),
                    outputs=_require_string_list(
                        module.get("outputs", []),
                        "method.modules.outputs",
                    ),
                )
            )
        return modules

    def _parse_experiments(self, raw: Any) -> list[ExperimentRecord]:
        data = _require_mapping(raw, "experiments")
        records = []
        for item in _require_list(data.get("experiments", []), "experiments"):
            record = _require_mapping(item, "experiments item")
            records.append(
                ExperimentRecord(
                    benchmark=_require_string(
                        record,
                        "benchmark",
                        "experiments.benchmark",
                    ),
                    setting=_require_string(record, "setting", "experiments.setting"),
                    metric=_require_string(record, "metric", "experiments.metric"),
                    method=_require_string(record, "method", "experiments.method"),
                    value=float(record["value"]),
                    higher_is_better=bool(record["higher_is_better"]),
                    source=_parse_evidence(record["source"], "experiments.source"),
                )
            )
        return records

    def _parse_topic_relation(
        self,
        raw: Any,
    ) -> tuple[TopicRelation, list[str], list[str]]:
        data = _require_mapping(raw, "topic_relation")
        relation = TopicRelation(
            relevance=_require_string(
                data,
                "relevance",
                "topic_relation.relevance",
            ),
            concept_axes=_require_string_list(
                data.get("concept_axes", []),
                "topic_relation.concept_axes",
            ),
            collision_risk=_require_string(
                data,
                "collision_risk",
                "topic_relation.collision_risk",
            ),
            differentiation=_require_string(
                data,
                "differentiation",
                "topic_relation.differentiation",
            ),
        )
        critique = _require_string_list(data.get("critique", []), "critique")
        follow_ups = _require_string_list(
            data.get("follow_up_questions", []),
            "follow_up_questions",
        )
        return relation, critique, follow_ups


def _pages_to_prompt_text(pages: list[PageText], max_chars: int = 60000) -> str:
    parts = [f"[Page {page.page}]\n{page.text.strip()}" for page in pages]
    text = "\n\n".join(parts)
    return text[:max_chars]


def _topic_to_prompt_text(topic: TopicProfile | None) -> str:
    if topic is None:
        return "No topic profile provided."
    axes = ", ".join(axis.name for axis in topic.concept_axes)
    return (
        f"Topic: {topic.name}\n"
        f"Intent: {topic.intent}\n"
        f"Concept axes: {axes}\n"
        f"Positive scope: {'; '.join(topic.scope.positive)}\n"
        f"Collision scope: {'; '.join(topic.scope.collision)}"
    )


def _parse_evidence(raw: Any, path: str) -> Evidence:
    data = _require_mapping(raw, path)
    return Evidence(
        text=_require_string(data, "text", f"{path}.text"),
        page=int(data["page"]),
        section=_require_string(data, "section", f"{path}.section"),
        quote=_require_string(data, "quote", f"{path}.quote"),
        confidence=_require_string(data, "confidence", f"{path}.confidence"),
    )


def _require_mapping(raw: Any, path: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must be an object")
    return raw


def _require_string(data: dict[str, Any], key: str, path: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{path} must be a string")
    return value


def _require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{path} must be a list")
    return value


def _require_string_list(value: Any, path: str) -> list[str]:
    items = _require_list(value, path)
    if not all(isinstance(item, str) for item in items):
        raise ValueError(f"{path} must be a list of strings")
    return items
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
python -m pytest tests/reader/test_staged_reader.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit**

```bash
git add src/reader/staged_reader.py tests/reader/test_staged_reader.py
git commit -m "feat: add staged paper reader"
```

## Task 4: Reading Package Renderer

**Files:**
- Create: `src/reader/reading_renderer.py`
- Test: `tests/reader/test_reading_renderer.py`

- [ ] **Step 1: Write failing renderer tests**

Create `tests/reader/test_reading_renderer.py`:

```python
from __future__ import annotations

import json

from src.reader.reading_renderer import render_reading_markdown, write_reading_package
from src.reader.staged_models import Evidence, PaperReadingPackage, PaperSummary


def make_package() -> PaperReadingPackage:
    return PaperReadingPackage(
        paper_id="sample_paper",
        title="Sample Paper",
        source_path="sample.txt",
        summary=PaperSummary(
            problem="The paper studies navigation decisions.",
            method="It scores candidate viewpoints.",
            takeaway="The key idea is learned utility over memory.",
            contributions=["Task-conditioned utility scoring"],
        ),
        claims=[
            Evidence(
                text="The method improves SPL.",
                page=2,
                section="Experiments",
                quote="The method improves SPL.",
                confidence="high",
            )
        ],
        critique=["Needs stronger baselines."],
        follow_up_questions=["How is utility supervised?"],
    )


def test_render_reading_markdown_contains_core_sections() -> None:
    markdown = render_reading_markdown(make_package())

    assert "# Sample Paper" in markdown
    assert "## One-Sentence Takeaway" in markdown
    assert "The key idea is learned utility over memory." in markdown
    assert "## Claims And Evidence" in markdown
    assert "The method improves SPL." in markdown
    assert "## Critical Assessment" in markdown


def test_write_reading_package_writes_json_and_markdown(tmp_path) -> None:
    json_path, markdown_path = write_reading_package(make_package(), tmp_path)

    assert json_path.name == "sample_paper.json"
    assert markdown_path.name == "sample_paper.reading.md"
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    assert raw["paper_id"] == "sample_paper"
    assert "# Sample Paper" in markdown_path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest tests/reader/test_reading_renderer.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'src.reader.reading_renderer'
```

- [ ] **Step 3: Implement renderer**

Create `src/reader/reading_renderer.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from src.reader.staged_models import PaperReadingPackage


def render_reading_markdown(package: PaperReadingPackage) -> str:
    lines = [
        f"# {package.title}",
        "",
        "## Metadata",
        f"- Paper ID: {package.paper_id}",
        f"- Source: {package.source_path}",
        "",
    ]
    if package.summary:
        lines.extend(
            [
                "## One-Sentence Takeaway",
                package.summary.takeaway,
                "",
                "## Problem",
                package.summary.problem,
                "",
                "## Method",
                package.summary.method,
                "",
                "## Key Contributions",
            ]
        )
        lines.extend(f"- {item}" for item in package.summary.contributions)
        lines.append("")

    lines.extend(["## Claims And Evidence", ""])
    if package.claims:
        lines.append("| Claim | Page | Section | Evidence | Confidence |")
        lines.append("|---|---:|---|---|---|")
        for claim in package.claims:
            lines.append(
                f"| {claim.text} | {claim.page} | {claim.section} | "
                f"{claim.quote} | {claim.confidence} |"
            )
    else:
        lines.append("No evidence-backed claims extracted.")
    lines.append("")

    lines.extend(["## Method Breakdown", ""])
    if package.method_modules:
        for module in package.method_modules:
            lines.extend(
                [
                    f"### {module.name}",
                    f"- Role: {module.role}",
                    f"- Inputs: {', '.join(module.inputs) or 'Not specified'}",
                    f"- Outputs: {', '.join(module.outputs) or 'Not specified'}",
                    "",
                ]
            )
    else:
        lines.append("No method modules extracted.")
        lines.append("")

    lines.extend(["## Experiments", ""])
    if package.experiments:
        lines.append("| Benchmark | Setting | Metric | Method | Value | Source |")
        lines.append("|---|---|---|---|---:|---|")
        for record in package.experiments:
            source = f"p.{record.source.page}, {record.source.section}"
            lines.append(
                f"| {record.benchmark} | {record.setting} | {record.metric} | "
                f"{record.method} | {record.value} | {source} |"
            )
    else:
        lines.append("No experiment records extracted.")
    lines.append("")

    lines.extend(["## Relation To Topic", ""])
    if package.topic_relation:
        relation = package.topic_relation
        lines.extend(
            [
                f"- Relevance: {relation.relevance}",
                f"- Concept axes: {', '.join(relation.concept_axes)}",
                f"- Collision risk: {relation.collision_risk}",
                f"- Differentiation: {relation.differentiation}",
            ]
        )
    else:
        lines.append("No topic profile was provided.")
    lines.append("")

    lines.extend(["## Critical Assessment", ""])
    if package.critique:
        lines.extend(f"- {item}" for item in package.critique)
    else:
        lines.append("No critique extracted.")
    lines.append("")

    lines.extend(["## Follow-Up", ""])
    if package.follow_up_questions:
        lines.extend(f"- {item}" for item in package.follow_up_questions)
    else:
        lines.append("No follow-up questions extracted.")
    lines.append("")

    return "\n".join(lines)


def write_reading_package(
    package: PaperReadingPackage,
    output_dir: Path,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{package.paper_id}.json"
    markdown_path = output_dir / f"{package.paper_id}.reading.md"
    json_path.write_text(
        json.dumps(package.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    markdown_path.write_text(render_reading_markdown(package), encoding="utf-8")
    return json_path, markdown_path
```

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
python -m pytest tests/reader/test_reading_renderer.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit**

```bash
git add src/reader/reading_renderer.py tests/reader/test_reading_renderer.py
git commit -m "feat: render staged reading packages"
```

## Task 5: Staged Read CLI

**Files:**
- Create: `src/reader/staged_cli.py`
- Modify: `run.py`
- Test: `tests/reader/test_staged_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/reader/test_staged_cli.py`:

```python
from __future__ import annotations

from run import build_parser


def test_read_staged_text_file_args() -> None:
    parser = build_parser()
    args = parser.parse_args(
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
    parser = build_parser()
    try:
        parser.parse_args(
            [
                "read",
                "--staged",
                "--paper-id",
                "sample",
                "--title",
                "Sample Paper",
            ]
        )
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("parser should reject staged read without source")
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
python -m pytest tests/reader/test_staged_cli.py -q
```

Expected:

```text
SystemExit: 2
```

The parser does not know the new staged options yet.

- [ ] **Step 3: Implement staged CLI handler**

Create `src/reader/staged_cli.py`:

```python
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.config import LLMConfig, load_config
from src.reader.page_extractor import extract_pages_from_pdf, extract_pages_from_text_file
from src.reader.reading_renderer import write_reading_package
from src.reader.staged_reader import StagedPaperReader
from src.survey.models import TopicProfile


async def cmd_read_staged(args) -> None:
    try:
        from src.llm.gemini_client import GeminiClient
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name == "google" or exc.name.startswith("google.")):
            raise SystemExit(
                "Error: google-genai is required for staged reading. "
                "Run pip install -r requirements.txt."
            ) from exc
        raise

    load_dotenv()
    app_config = load_config(args.config)
    api_key = os.environ.get("GEMINI_API_KEY", "") or app_config.llm.api_key
    if not api_key:
        raise SystemExit("Error: GEMINI_API_KEY environment variable not set.")

    source_path = Path(args.pdf or args.text_file)
    if args.pdf:
        pages = extract_pages_from_pdf(source_path)
    else:
        pages = extract_pages_from_text_file(source_path)

    topic = _load_topic(Path(args.topic)) if args.topic else None
    output_dir = _resolve_output_dir(args, topic)
    llm_config = LLMConfig(
        filter_model=app_config.llm.filter_model,
        reader_model=app_config.llm.reader_model,
        embedding_model=app_config.llm.embedding_model,
        api_key=api_key,
        max_concurrent=app_config.llm.max_concurrent,
        temperature=app_config.llm.temperature,
    )
    reader = StagedPaperReader(GeminiClient(llm_config), model=llm_config.reader_model)
    package = await reader.read(
        paper_id=args.paper_id,
        title=args.title,
        source_path=str(source_path),
        pages=pages,
        topic=topic,
    )
    json_path, markdown_path = write_reading_package(package, output_dir)
    print(f"Reading JSON: {json_path}")
    print(f"Reading Markdown: {markdown_path}")


def run_read_staged(args) -> None:
    asyncio.run(cmd_read_staged(args))


def _load_topic(path: Path) -> TopicProfile:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return TopicProfile.from_dict(raw)


def _resolve_output_dir(args, topic: TopicProfile | None) -> Path:
    if args.topic:
        return Path(args.topic).parent / "papers"
    return Path(args.output_root or "data/readings")
```

- [ ] **Step 4: Extend `run.py` parser and routing**

Modify the existing `read_parser` setup inside `build_parser()`:

```python
    read_parser = subparsers.add_parser("read", help="Deep-read a specific paper")
    read_parser.add_argument(
        "arxiv_id",
        nargs="?",
        help="ArXiv paper ID (e.g. 2401.12345)",
    )
    read_parser.add_argument(
        "--staged",
        action="store_true",
        help="Use the staged local paper reader",
    )
    read_source = read_parser.add_mutually_exclusive_group()
    read_source.add_argument("--pdf", help="Local PDF path for staged reading")
    read_source.add_argument("--text-file", help="Local text file for staged reading")
    read_parser.add_argument("--paper-id", help="Paper id for staged output files")
    read_parser.add_argument("--title", help="Paper title for staged reading")
    read_parser.add_argument("--topic", help="Topic profile YAML path")
    read_parser.add_argument(
        "--output-root",
        default="data/readings",
        help="Output root when no topic profile is provided",
    )
```

Update `PaperReaderArgumentParser.parse_args()` to validate staged read arguments:

```python
        if getattr(parsed, "command", None) == "read" and getattr(parsed, "staged", False):
            has_source = bool(getattr(parsed, "pdf", None) or getattr(parsed, "text_file", None))
            if not has_source:
                self.error("read --staged requires exactly one of --pdf or --text-file")
            if not getattr(parsed, "paper_id", None):
                self.error("read --staged requires --paper-id")
            if not getattr(parsed, "title", None):
                self.error("read --staged requires --title")
```

Update `main()` before regular config loading:

```python
    if args.command == "read" and getattr(args, "staged", False):
        from src.reader.staged_cli import run_read_staged

        run_read_staged(args)
        return
```

Keep the existing non-staged `read` command path unchanged.

- [ ] **Step 5: Run CLI tests and verify pass**

Run:

```bash
python -m pytest tests/reader/test_staged_cli.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 6: Commit**

```bash
git add run.py src/reader/staged_cli.py tests/reader/test_staged_cli.py
git commit -m "feat: add staged read CLI"
```

## Task 6: Staged Reader Workflow Smoke Test

**Files:**
- Test: `tests/reader/test_staged_workflow.py`

- [ ] **Step 1: Write fake workflow test**

Create `tests/reader/test_staged_workflow.py`:

```python
from __future__ import annotations

from typing import Any

import pytest

from src.reader.page_extractor import extract_pages_from_text_file
from src.reader.reading_renderer import write_reading_package
from src.reader.staged_reader import StagedPaperReader


class FakeLLM:
    async def generate_json(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float | None = None,
    ) -> Any:
        if "Stage: summary" in prompt:
            return {
                "problem": "Navigation methods need better 3D decisions.",
                "method": "The paper scores candidates from memory.",
                "takeaway": "Utility scoring is the central mechanism.",
                "contributions": ["A staged utility model"],
            }
        if "Stage: section_notes" in prompt:
            return {"claims": []}
        if "Stage: method" in prompt:
            return {"modules": []}
        if "Stage: experiments" in prompt:
            return {"experiments": []}
        if "Stage: topic_relation" in prompt:
            return {
                "relevance": "core",
                "concept_axes": [],
                "collision_risk": "low",
                "differentiation": "Synthetic test relation.",
                "critique": [],
                "follow_up_questions": [],
            }
        raise AssertionError("unexpected prompt")


@pytest.mark.asyncio
async def test_text_file_to_reading_artifacts(tmp_path) -> None:
    text_path = tmp_path / "paper.txt"
    text_path.write_text(
        "Abstract\nThis paper studies navigation.\n\nExperiments\nNo table.",
        encoding="utf-8",
    )
    pages = extract_pages_from_text_file(text_path)
    reader = StagedPaperReader(FakeLLM(), model="gemini-2.5-pro")

    package = await reader.read(
        paper_id="sample",
        title="Sample Paper",
        source_path=str(text_path),
        pages=pages,
        topic=None,
    )
    json_path, markdown_path = write_reading_package(package, tmp_path / "out")

    assert json_path.exists()
    assert markdown_path.exists()
    assert "Utility scoring is the central mechanism." in markdown_path.read_text(
        encoding="utf-8"
    )
```

- [ ] **Step 2: Run workflow test and verify pass**

Run:

```bash
python -m pytest tests/reader/test_staged_workflow.py -q
```

Expected:

```text
1 passed
```

- [ ] **Step 3: Run all reader tests**

Run:

```bash
python -m pytest tests/reader -q
```

Expected:

```text
11 passed
```

- [ ] **Step 4: Commit**

```bash
git add tests/reader/test_staged_workflow.py
git commit -m "test: cover staged reading workflow"
```

## Task 7: Manual CLI Smoke Test

**Files:**
- No code changes expected.

- [ ] **Step 1: Verify help output**

Run:

```bash
python run.py read --help
```

Expected output contains:

```text
--staged
--pdf
--text-file
--paper-id
--title
--topic
```

- [ ] **Step 2: Create local smoke input**

Run:

```bash
New-Item -ItemType Directory -Force data/smoke | Out-Null
Set-Content -Path data/smoke/sample_paper.txt -Value "Abstract`nThis paper studies task-driven navigation utility.`n`nExperiments`nSampleNav obtains 35.1 SPL." -Encoding UTF8
```

- [ ] **Step 3: Run real staged reading smoke**

Run:

```bash
python run.py read --staged --text-file data/smoke/sample_paper.txt --paper-id sample_paper --title "Sample Paper" --output-root data/readings-smoke
```

Expected output:

```text
Reading JSON: data\readings-smoke\sample_paper.json
Reading Markdown: data\readings-smoke\sample_paper.reading.md
```

If the command is blocked by invalid or missing `GEMINI_API_KEY`, report the blocker and do not claim the real LLM path passed.

- [ ] **Step 4: Inspect generated files when smoke succeeds**

Run:

```bash
Get-ChildItem -Recurse data/readings-smoke
```

Expected files:

```text
sample_paper.json
sample_paper.reading.md
```

- [ ] **Step 5: Do not commit generated smoke data**

Confirm:

```bash
git status --short
```

Expected tracked files are clean. Generated `data/` files are ignored.

## Task 8: Final Verification

**Files:**
- No code changes expected.

- [ ] **Step 1: Run all tests**

Run:

```bash
python -m pytest -q
```

Expected:

```text
All tests pass with the final test count printed by pytest.
```

- [ ] **Step 2: Run compile check**

Run:

```bash
python -m compileall src run.py
```

Expected:

```text
The command exits with status 0.
```

- [ ] **Step 3: Check staged CLI imports**

Run:

```bash
python -c "import src.reader.staged_cli"
```

Expected:

```text
The command exits with status 0.
```

This ensures `google-genai` is not imported at module import time.

- [ ] **Step 4: Check git status**

Run:

```bash
git status --short
```

Expected tracked changes are committed. Ignored smoke data under `data/` may exist but should not appear.

## Self-Review

Spec coverage:

- Page-aware extraction is covered by Task 2.
- Staged reading schemas are covered by Task 1.
- Staged LLM reading is covered by Task 3.
- Markdown and JSON outputs are covered by Task 4.
- CLI staged local reading is covered by Task 5.
- End-to-end fake workflow is covered by Task 6.
- Manual real LLM smoke is covered by Task 7.

Known deferred work:

- ArXiv-id staged reading is deferred until the staged reader package is stable.
- Survey synthesis over multiple reading packages belongs to MVP-3.
- Structured SOTA persistence belongs to MVP-4.
- Replacing the old pipeline `DeepReader` is intentionally deferred to avoid breaking existing commands.
