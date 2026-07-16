# MVP-3 Survey Synthesis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `survey synthesize`, an offline workflow that turns `topic.yaml` plus staged reading package JSON files into updated survey artifacts.

**Architecture:** Add a focused survey synthesis layer on top of MVP-1 topic artifacts and MVP-2 reading packages. The workflow loads validated reading packages, asks an LLM for structured synthesis, renders four Markdown auto-blocks, and updates artifacts only after the full synthesis object validates.

**Tech Stack:** Python dataclasses, pathlib/json/yaml, existing `TopicArtifactManager`, existing `TopicProfile` and `PaperReadingPackage`, pytest, Gemini JSON mode via existing `GeminiClient`.

---

## Scope

This plan implements MVP-3 only:

- offline synthesis from existing reading package JSON files;
- `python run.py survey synthesize --topic <topic.yaml>`;
- optional `--readings-dir` override;
- structured synthesis schema validation;
- Markdown auto-block updates for `survey.md`, `papers.md`, `positioning.md`, `references.md`;
- audit event append to `state/survey_events.jsonl`;
- fake LLM workflow tests;
- manual smoke with the local PDF corpus under `data/pdfs/mvp3-smoke/`.

This plan does not implement paper search, citation expansion, recurring tracking, or structured SOTA.

## File Structure

- Create `src/survey/synthesis_models.py`
  - Dataclasses for structured survey synthesis output.
  - `to_dict()` / `from_dict()` methods with strict-enough validation and bounded normalization.
- Create `src/survey/reading_loader.py`
  - Load `PaperReadingPackage` JSON files from a directory.
  - Reject missing directories, empty directories, malformed JSON, malformed reading packages, duplicate `paper_id`.
- Create `src/survey/survey_renderer.py`
  - Render `SurveySynthesis` sections to Markdown strings for existing auto-blocks.
- Create `src/survey/synthesizer.py`
  - Build prompt from `TopicProfile` + reading packages.
  - Call async LLM protocol `generate_json`.
  - Validate unknown paper references against loaded paper ids.
- Modify `src/survey/cli.py`
  - Add `cmd_survey_synthesize(args)` and route it from `run_survey_command`.
  - Lazy import `GeminiClient`.
  - Validate inputs before LLM call.
- Modify `run.py`
  - Add `survey synthesize` parser and argument validation.
- Add tests:
  - `tests/survey/test_synthesis_models.py`
  - `tests/survey/test_reading_loader.py`
  - `tests/survey/test_survey_renderer.py`
  - `tests/survey/test_synthesizer.py`
  - Extend `tests/survey/test_cli.py`
  - Add `tests/survey/test_synthesize_workflow.py`

---

## Task 1: Survey Synthesis Models

**Files:**
- Create: `src/survey/synthesis_models.py`
- Test: `tests/survey/test_synthesis_models.py`

- [ ] **Step 1: Write failing tests for synthesis models**

Create `tests/survey/test_synthesis_models.py`:

```python
from __future__ import annotations

import pytest

from src.survey.synthesis_models import (
    PaperClassification,
    PositioningSynthesis,
    ReferenceEntry,
    SurveySynthesis,
    TaxonomyGroup,
)


def _raw_synthesis() -> dict:
    return {
        "taxonomy": [
            {
                "name": "Explicit utility models",
                "description": "Methods that score action candidates.",
                "paper_ids": ["mtu3d"],
                "key_distinction": "They expose a decision score.",
            }
        ],
        "paper_map": [
            {
                "paper_id": "mtu3d",
                "title": "Move to Understand a 3D Scene",
                "role": "collision",
                "rationale": "It already scores objects and frontiers.",
                "evidence": "Scores object/frontier candidates.",
            }
        ],
        "positioning": {
            "thesis_gap": "Learn task-conditioned utility over 3D memory.",
            "novelty_claim": "Generalize beyond object/frontier scoring.",
            "collision_risks": ["MTU3D may overlap."],
            "recommended_positioning": "Focus on explicit utility learning.",
        },
        "references": [
            {
                "paper_id": "mtu3d",
                "title": "Move to Understand a 3D Scene",
                "why_relevant": "Closest collision paper.",
                "evidence": "Candidate scoring.",
            }
        ],
        "open_questions": ["How is utility supervised?"],
    }


def test_survey_synthesis_round_trips() -> None:
    synthesis = SurveySynthesis.from_dict(_raw_synthesis())

    assert synthesis.taxonomy[0] == TaxonomyGroup(
        name="Explicit utility models",
        description="Methods that score action candidates.",
        paper_ids=["mtu3d"],
        key_distinction="They expose a decision score.",
    )
    assert synthesis.paper_map[0] == PaperClassification(
        paper_id="mtu3d",
        title="Move to Understand a 3D Scene",
        role="collision",
        rationale="It already scores objects and frontiers.",
        evidence="Scores object/frontier candidates.",
    )
    assert synthesis.positioning == PositioningSynthesis(
        thesis_gap="Learn task-conditioned utility over 3D memory.",
        novelty_claim="Generalize beyond object/frontier scoring.",
        collision_risks=["MTU3D may overlap."],
        recommended_positioning="Focus on explicit utility learning.",
    )
    assert synthesis.references[0] == ReferenceEntry(
        paper_id="mtu3d",
        title="Move to Understand a 3D Scene",
        why_relevant="Closest collision paper.",
        evidence="Candidate scoring.",
    )
    assert synthesis.to_dict()["open_questions"] == ["How is utility supervised?"]


def test_survey_synthesis_accepts_single_string_lists() -> None:
    raw = _raw_synthesis()
    raw["taxonomy"][0]["paper_ids"] = "mtu3d"
    raw["positioning"]["collision_risks"] = "MTU3D may overlap."
    raw["open_questions"] = "How is utility supervised?"

    synthesis = SurveySynthesis.from_dict(raw)

    assert synthesis.taxonomy[0].paper_ids == ["mtu3d"]
    assert synthesis.positioning.collision_risks == ["MTU3D may overlap."]
    assert synthesis.open_questions == ["How is utility supervised?"]


def test_survey_synthesis_rejects_unknown_role() -> None:
    raw = _raw_synthesis()
    raw["paper_map"][0]["role"] = "unrelated"

    with pytest.raises(ValueError, match="paper_map\\[0\\]\\.role"):
        SurveySynthesis.from_dict(raw)


def test_survey_synthesis_requires_top_level_sections() -> None:
    raw = _raw_synthesis()
    del raw["taxonomy"]

    with pytest.raises(ValueError, match="taxonomy is required"):
        SurveySynthesis.from_dict(raw)
```

- [ ] **Step 2: Run model tests and verify RED**

Run:

```bash
python -m pytest tests/survey/test_synthesis_models.py -q
```

Expected: fails with `ModuleNotFoundError: No module named 'src.survey.synthesis_models'`.

- [ ] **Step 3: Implement synthesis models**

Create `src/survey/synthesis_models.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


ALLOWED_PAPER_ROLES = {"core", "adjacent", "collision", "background"}


@dataclass(frozen=True)
class TaxonomyGroup:
    name: str
    description: str
    paper_ids: list[str] = field(default_factory=list)
    key_distinction: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any], path: str = "taxonomy[]") -> "TaxonomyGroup":
        mapping = _require_mapping(raw, path)
        return cls(
            name=_require_string(_required(mapping, "name", f"{path}.name"), f"{path}.name"),
            description=_require_string(
                _required(mapping, "description", f"{path}.description"),
                f"{path}.description",
            ),
            paper_ids=_string_list(mapping.get("paper_ids", []), f"{path}.paper_ids"),
            key_distinction=_require_string(
                _required(mapping, "key_distinction", f"{path}.key_distinction"),
                f"{path}.key_distinction",
            ),
        )


@dataclass(frozen=True)
class PaperClassification:
    paper_id: str
    title: str
    role: str
    rationale: str
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(
        cls, raw: dict[str, Any], path: str = "paper_map[]"
    ) -> "PaperClassification":
        mapping = _require_mapping(raw, path)
        role = _require_string(_required(mapping, "role", f"{path}.role"), f"{path}.role")
        if role not in ALLOWED_PAPER_ROLES:
            raise ValueError(f"{path}.role must be one of {sorted(ALLOWED_PAPER_ROLES)}")
        return cls(
            paper_id=_require_string(
                _required(mapping, "paper_id", f"{path}.paper_id"), f"{path}.paper_id"
            ),
            title=_require_string(_required(mapping, "title", f"{path}.title"), f"{path}.title"),
            role=role,
            rationale=_require_string(
                _required(mapping, "rationale", f"{path}.rationale"), f"{path}.rationale"
            ),
            evidence=_optional_string(mapping.get("evidence", ""), f"{path}.evidence"),
        )


@dataclass(frozen=True)
class PositioningSynthesis:
    thesis_gap: str
    novelty_claim: str
    collision_risks: list[str] = field(default_factory=list)
    recommended_positioning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(
        cls, raw: dict[str, Any], path: str = "positioning"
    ) -> "PositioningSynthesis":
        mapping = _require_mapping(raw, path)
        return cls(
            thesis_gap=_require_string(
                _required(mapping, "thesis_gap", f"{path}.thesis_gap"),
                f"{path}.thesis_gap",
            ),
            novelty_claim=_require_string(
                _required(mapping, "novelty_claim", f"{path}.novelty_claim"),
                f"{path}.novelty_claim",
            ),
            collision_risks=_string_list(
                mapping.get("collision_risks", []), f"{path}.collision_risks"
            ),
            recommended_positioning=_require_string(
                _required(
                    mapping,
                    "recommended_positioning",
                    f"{path}.recommended_positioning",
                ),
                f"{path}.recommended_positioning",
            ),
        )


@dataclass(frozen=True)
class ReferenceEntry:
    paper_id: str
    title: str
    why_relevant: str
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any], path: str = "references[]") -> "ReferenceEntry":
        mapping = _require_mapping(raw, path)
        return cls(
            paper_id=_require_string(
                _required(mapping, "paper_id", f"{path}.paper_id"), f"{path}.paper_id"
            ),
            title=_require_string(_required(mapping, "title", f"{path}.title"), f"{path}.title"),
            why_relevant=_require_string(
                _required(mapping, "why_relevant", f"{path}.why_relevant"),
                f"{path}.why_relevant",
            ),
            evidence=_optional_string(mapping.get("evidence", ""), f"{path}.evidence"),
        )


@dataclass(frozen=True)
class SurveySynthesis:
    taxonomy: list[TaxonomyGroup] = field(default_factory=list)
    paper_map: list[PaperClassification] = field(default_factory=list)
    positioning: PositioningSynthesis = field(
        default_factory=lambda: PositioningSynthesis(
            thesis_gap="",
            novelty_claim="",
            collision_risks=[],
            recommended_positioning="",
        )
    )
    references: list[ReferenceEntry] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "taxonomy": [group.to_dict() for group in self.taxonomy],
            "paper_map": [item.to_dict() for item in self.paper_map],
            "positioning": self.positioning.to_dict(),
            "references": [entry.to_dict() for entry in self.references],
            "open_questions": list(self.open_questions),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SurveySynthesis":
        mapping = _require_mapping(raw, "survey_synthesis")
        taxonomy_raw = _require_list(_required(mapping, "taxonomy", "taxonomy"), "taxonomy")
        paper_map_raw = _require_list(_required(mapping, "paper_map", "paper_map"), "paper_map")
        references_raw = _require_list(
            _required(mapping, "references", "references"), "references"
        )
        return cls(
            taxonomy=[
                TaxonomyGroup.from_dict(item, f"taxonomy[{index}]")
                for index, item in enumerate(taxonomy_raw)
            ],
            paper_map=[
                PaperClassification.from_dict(item, f"paper_map[{index}]")
                for index, item in enumerate(paper_map_raw)
            ],
            positioning=PositioningSynthesis.from_dict(
                _required(mapping, "positioning", "positioning")
            ),
            references=[
                ReferenceEntry.from_dict(item, f"references[{index}]")
                for index, item in enumerate(references_raw)
            ],
            open_questions=_string_list(mapping.get("open_questions", []), "open_questions"),
        )


def _required(raw: dict[str, Any], key: str, path: str) -> Any:
    if key not in raw:
        raise ValueError(f"{path} is required")
    return raw[key]


def _require_mapping(raw: Any, path: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
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


def _optional_string(raw: Any, path: str) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ValueError(f"{path} must be a string")
    return raw


def _string_list(raw: Any, path: str) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    items = _require_list(raw, path)
    for index, item in enumerate(items):
        _require_string(item, f"{path}[{index}]")
    return items
```

- [ ] **Step 4: Run model tests and verify GREEN**

Run:

```bash
python -m pytest tests/survey/test_synthesis_models.py -q
```

Expected:

```text
4 passed
```

- [ ] **Step 5: Commit**

Run:

```bash
git add src/survey/synthesis_models.py tests/survey/test_synthesis_models.py
git commit -m "feat: add survey synthesis models"
```

---

## Task 2: Reading Package Loader

**Files:**
- Create: `src/survey/reading_loader.py`
- Test: `tests/survey/test_reading_loader.py`

- [ ] **Step 1: Write failing loader tests**

Create `tests/survey/test_reading_loader.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.reader.staged_models import PaperReadingPackage, PaperSummary
from src.survey.reading_loader import load_reading_packages


def _package(paper_id: str, title: str) -> PaperReadingPackage:
    return PaperReadingPackage(
        paper_id=paper_id,
        title=title,
        source_path=f"papers/{paper_id}.pdf",
        summary=PaperSummary(
            problem="Navigation needs better decision models.",
            method="The paper scores candidate actions.",
            takeaway=f"{title} is relevant to utility-based navigation.",
            contributions=["Candidate scoring"],
        ),
    )


def _write_package(directory: Path, package: PaperReadingPackage) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{package.paper_id}.json").write_text(
        json.dumps(package.to_dict()), encoding="utf-8"
    )


def test_load_reading_packages_sorted_by_paper_id(tmp_path) -> None:
    _write_package(tmp_path, _package("vlfm", "VLFM"))
    _write_package(tmp_path, _package("mtu3d", "MTU3D"))

    packages = load_reading_packages(tmp_path)

    assert [package.paper_id for package in packages] == ["mtu3d", "vlfm"]


def test_load_reading_packages_rejects_missing_directory(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="Readings directory not found"):
        load_reading_packages(tmp_path / "missing")


def test_load_reading_packages_rejects_empty_directory(tmp_path) -> None:
    tmp_path.mkdir(exist_ok=True)

    with pytest.raises(ValueError, match="No reading package JSON files found"):
        load_reading_packages(tmp_path)


def test_load_reading_packages_rejects_duplicate_paper_ids(tmp_path) -> None:
    _write_package(tmp_path, _package("mtu3d", "MTU3D"))
    (tmp_path / "copy.json").write_text(
        json.dumps(_package("mtu3d", "MTU3D Copy").to_dict()), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Duplicate paper_id: mtu3d"):
        load_reading_packages(tmp_path)


def test_load_reading_packages_rejects_malformed_json(tmp_path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid reading package JSON"):
        load_reading_packages(tmp_path)
```

- [ ] **Step 2: Run loader tests and verify RED**

Run:

```bash
python -m pytest tests/survey/test_reading_loader.py -q
```

Expected: fails with `ModuleNotFoundError: No module named 'src.survey.reading_loader'`.

- [ ] **Step 3: Implement loader**

Create `src/survey/reading_loader.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from src.reader.staged_models import PaperReadingPackage


def load_reading_packages(readings_dir: Path) -> list[PaperReadingPackage]:
    if not readings_dir.exists() or not readings_dir.is_dir():
        raise FileNotFoundError(f"Readings directory not found: {readings_dir}")

    json_paths = sorted(readings_dir.glob("*.json"))
    if not json_paths:
        raise ValueError(f"No reading package JSON files found in {readings_dir}")

    packages = []
    seen_ids = set()
    for path in json_paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid reading package JSON {path}: {exc}") from exc

        try:
            package = PaperReadingPackage.from_dict(raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Malformed reading package {path}: {exc}") from exc

        if package.paper_id in seen_ids:
            raise ValueError(f"Duplicate paper_id: {package.paper_id}")
        seen_ids.add(package.paper_id)
        packages.append(package)

    return sorted(packages, key=lambda package: package.paper_id)
```

- [ ] **Step 4: Run loader tests and verify GREEN**

Run:

```bash
python -m pytest tests/survey/test_reading_loader.py -q
```

Expected:

```text
5 passed
```

- [ ] **Step 5: Commit**

Run:

```bash
git add src/survey/reading_loader.py tests/survey/test_reading_loader.py
git commit -m "feat: load survey reading packages"
```

---

## Task 3: Survey Markdown Renderer

**Files:**
- Create: `src/survey/survey_renderer.py`
- Test: `tests/survey/test_survey_renderer.py`

- [ ] **Step 1: Write failing renderer tests**

Create `tests/survey/test_survey_renderer.py`:

```python
from __future__ import annotations

from src.survey.survey_renderer import (
    render_paper_map_markdown,
    render_positioning_markdown,
    render_references_markdown,
    render_taxonomy_markdown,
)
from src.survey.synthesis_models import (
    PaperClassification,
    PositioningSynthesis,
    ReferenceEntry,
    SurveySynthesis,
    TaxonomyGroup,
)


def _synthesis() -> SurveySynthesis:
    return SurveySynthesis(
        taxonomy=[
            TaxonomyGroup(
                name="Explicit utility models",
                description="Score candidate actions.",
                paper_ids=["mtu3d"],
                key_distinction="Exposes learned decision scores.",
            )
        ],
        paper_map=[
            PaperClassification(
                paper_id="mtu3d",
                title="MTU3D",
                role="collision",
                rationale="Already scores object/frontier candidates.",
                evidence="Candidate scoring.",
            )
        ],
        positioning=PositioningSynthesis(
            thesis_gap="Task-conditioned utility over 3D memory is underexplored.",
            novelty_claim="Learn utility over richer 3D primitives.",
            collision_risks=["MTU3D overlaps on candidate scoring."],
            recommended_positioning="Emphasize generalized utility learning.",
        ),
        references=[
            ReferenceEntry(
                paper_id="mtu3d",
                title="MTU3D",
                why_relevant="Closest collision work.",
                evidence="Candidate scoring.",
            )
        ],
        open_questions=["How should utility be supervised?"],
    )


def test_render_taxonomy_markdown() -> None:
    markdown = render_taxonomy_markdown(_synthesis())

    assert "## Method Groups" in markdown
    assert "Explicit utility models" in markdown
    assert "`mtu3d`" in markdown
    assert "How should utility be supervised?" in markdown


def test_render_paper_map_markdown_groups_by_role() -> None:
    markdown = render_paper_map_markdown(_synthesis())

    assert "## Collision" in markdown
    assert "MTU3D" in markdown
    assert "Already scores object/frontier candidates." in markdown


def test_render_positioning_markdown() -> None:
    markdown = render_positioning_markdown(_synthesis())

    assert "## Thesis Gap" in markdown
    assert "Task-conditioned utility" in markdown
    assert "## Collision Risks" in markdown


def test_render_references_markdown_escapes_table_pipes() -> None:
    synthesis = _synthesis()
    synthesis.references[0] = ReferenceEntry(
        paper_id="mtu3d",
        title="MTU3D | navigation",
        why_relevant="Closest | collision",
        evidence="Score | candidates",
    )

    markdown = render_references_markdown(synthesis)

    assert "MTU3D \\| navigation" in markdown
    assert "Closest \\| collision" in markdown
```

- [ ] **Step 2: Run renderer tests and verify RED**

Run:

```bash
python -m pytest tests/survey/test_survey_renderer.py -q
```

Expected: fails with `ModuleNotFoundError: No module named 'src.survey.survey_renderer'`.

- [ ] **Step 3: Implement renderer**

Create `src/survey/survey_renderer.py`:

```python
from __future__ import annotations

from src.survey.synthesis_models import SurveySynthesis


ROLE_HEADINGS = {
    "core": "Core",
    "adjacent": "Adjacent",
    "collision": "Collision",
    "background": "Background",
}


def render_taxonomy_markdown(synthesis: SurveySynthesis) -> str:
    lines = ["## Method Groups", ""]
    if not synthesis.taxonomy:
        lines.append("No taxonomy groups were generated.")
    for group in synthesis.taxonomy:
        lines.extend(
            [
                f"### {group.name}",
                "",
                group.description,
                "",
                f"- Papers: {_format_ids(group.paper_ids)}",
                f"- Key distinction: {group.key_distinction}",
                "",
            ]
        )
    lines.extend(["## Open Questions", ""])
    lines.extend(_list_or_na(synthesis.open_questions))
    return _finish(lines)


def render_paper_map_markdown(synthesis: SurveySynthesis) -> str:
    lines = []
    for role, heading in ROLE_HEADINGS.items():
        items = [item for item in synthesis.paper_map if item.role == role]
        lines.extend([f"## {heading}", ""])
        if not items:
            lines.extend(["N/A", ""])
            continue
        for item in items:
            lines.extend(
                [
                    f"### {item.title} (`{item.paper_id}`)",
                    "",
                    f"- Rationale: {item.rationale}",
                    f"- Evidence: {item.evidence or 'N/A'}",
                    "",
                ]
            )
    return _finish(lines)


def render_positioning_markdown(synthesis: SurveySynthesis) -> str:
    positioning = synthesis.positioning
    lines = [
        "## Thesis Gap",
        "",
        positioning.thesis_gap,
        "",
        "## Novelty Claim",
        "",
        positioning.novelty_claim,
        "",
        "## Recommended Positioning",
        "",
        positioning.recommended_positioning,
        "",
        "## Collision Risks",
        "",
    ]
    lines.extend(_list_or_na(positioning.collision_risks))
    return _finish(lines)


def render_references_markdown(synthesis: SurveySynthesis) -> str:
    rows = [
        [
            f"`{entry.paper_id}`",
            entry.title,
            entry.why_relevant,
            entry.evidence or "N/A",
        ]
        for entry in synthesis.references
    ]
    return _finish(_markdown_table(["Paper ID", "Title", "Why Relevant", "Evidence"], rows))


def _format_ids(paper_ids: list[str]) -> str:
    if not paper_ids:
        return "N/A"
    return ", ".join(f"`{paper_id}`" for paper_id in paper_ids)


def _list_or_na(values: list[str]) -> list[str]:
    if not values:
        return ["N/A"]
    return [f"- {value}" for value in values]


def _markdown_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    if not rows:
        return ["N/A"]
    return [
        _markdown_table_row(headers),
        _markdown_table_row(["---"] * len(headers)),
        *[_markdown_table_row(row) for row in rows],
    ]


def _markdown_table_row(values: list[str]) -> str:
    return "| " + " | ".join(_escape_table_cell(value) for value in values) + " |"


def _escape_table_cell(value: str) -> str:
    normalized = str(value).replace("\r\n", "\n").replace("\r", "\n")
    return normalized.replace("\n", "<br>").replace("|", r"\|")


def _finish(lines: list[str]) -> str:
    return "\n".join(lines).rstrip() + "\n"
```

- [ ] **Step 4: Run renderer tests and verify GREEN**

Run:

```bash
python -m pytest tests/survey/test_survey_renderer.py -q
```

Expected:

```text
4 passed
```

- [ ] **Step 5: Commit**

Run:

```bash
git add src/survey/survey_renderer.py tests/survey/test_survey_renderer.py
git commit -m "feat: render survey synthesis artifacts"
```

---

## Task 4: LLM Survey Synthesizer

**Files:**
- Create: `src/survey/synthesizer.py`
- Test: `tests/survey/test_synthesizer.py`

- [ ] **Step 1: Write failing synthesizer tests**

Create `tests/survey/test_synthesizer.py`:

```python
from __future__ import annotations

from typing import Any, Optional

import pytest

from src.reader.staged_models import PaperReadingPackage, PaperSummary, TopicRelation
from src.survey.models import ConceptAxis, TopicProfile, TopicScope
from src.survey.synthesizer import SurveySynthesizer


def _topic() -> TopicProfile:
    return TopicProfile(
        topic_id="utility_nav",
        name="Utility Navigation",
        description="Task-conditioned utility over 3D memory.",
        intent="Find a thesis gap.",
        concept_axes=[ConceptAxis(name="utility", description="Candidate scoring.")],
        scope=TopicScope(positive=["ObjectNav"], collision=["MTU3D"]),
        open_questions=["How is utility supervised?"],
    )


def _package(paper_id: str, title: str, relevance: str = "core") -> PaperReadingPackage:
    return PaperReadingPackage(
        paper_id=paper_id,
        title=title,
        source_path=f"{paper_id}.pdf",
        summary=PaperSummary(
            problem="Navigation requires decisions.",
            method="Scores candidates.",
            takeaway=f"{title} is relevant.",
            contributions=["Candidate scoring"],
        ),
        topic_relation=TopicRelation(
            relevance=relevance,
            concept_axes=["utility"],
            collision_risk="medium",
            differentiation="Uses explicit scoring.",
        ),
        critique=["Needs stronger analysis."],
        follow_up_questions=["What supervision is used?"],
    )


class FakeLLM:
    def __init__(self, raw: Optional[dict[str, Any]] = None) -> None:
        self.prompts: list[str] = []
        self.calls: list[tuple[Optional[str], Optional[float]]] = []
        self.raw = raw or {
            "taxonomy": [
                {
                    "name": "Explicit utility models",
                    "description": "Score candidate actions.",
                    "paper_ids": ["mtu3d"],
                    "key_distinction": "Exposes a decision score.",
                }
            ],
            "paper_map": [
                {
                    "paper_id": "mtu3d",
                    "title": "MTU3D",
                    "role": "collision",
                    "rationale": "Closest overlap.",
                    "evidence": "Scores candidates.",
                }
            ],
            "positioning": {
                "thesis_gap": "General utility over 3D memory.",
                "novelty_claim": "Beyond object/frontier scoring.",
                "collision_risks": ["MTU3D overlap."],
                "recommended_positioning": "Emphasize task-conditioned utility.",
            },
            "references": [
                {
                    "paper_id": "mtu3d",
                    "title": "MTU3D",
                    "why_relevant": "Collision paper.",
                    "evidence": "Scores candidates.",
                }
            ],
            "open_questions": ["How is utility supervised?"],
        }

    async def generate_json(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        self.prompts.append(prompt)
        self.calls.append((model, temperature))
        return self.raw


@pytest.mark.asyncio
async def test_synthesizer_builds_synthesis() -> None:
    llm = FakeLLM()
    synthesizer = SurveySynthesizer(llm=llm, model="test-model")

    synthesis = await synthesizer.synthesize(_topic(), [_package("mtu3d", "MTU3D")])

    assert synthesis.taxonomy[0].name == "Explicit utility models"
    assert synthesis.paper_map[0].paper_id == "mtu3d"
    assert llm.calls == [("test-model", 0.1)]
    assert "## Topic" in llm.prompts[0]
    assert "Utility Navigation" in llm.prompts[0]
    assert "## Reading Packages" in llm.prompts[0]
    assert "MTU3D" in llm.prompts[0]
    assert "## Output Schema" in llm.prompts[0]


@pytest.mark.asyncio
async def test_synthesizer_rejects_unknown_paper_reference() -> None:
    llm = FakeLLM(
        raw={
            **FakeLLM().raw,
            "paper_map": [
                {
                    "paper_id": "unknown",
                    "title": "Unknown",
                    "role": "core",
                    "rationale": "Bad reference.",
                    "evidence": "",
                }
            ],
        }
    )
    synthesizer = SurveySynthesizer(llm=llm, model="test-model")

    with pytest.raises(ValueError, match="unknown paper_id"):
        await synthesizer.synthesize(_topic(), [_package("mtu3d", "MTU3D")])


@pytest.mark.asyncio
async def test_synthesizer_rejects_empty_packages() -> None:
    synthesizer = SurveySynthesizer(llm=FakeLLM(), model="test-model")

    with pytest.raises(ValueError, match="At least one reading package"):
        await synthesizer.synthesize(_topic(), [])
```

- [ ] **Step 2: Run synthesizer tests and verify RED**

Run:

```bash
python -m pytest tests/survey/test_synthesizer.py -q
```

Expected: fails with `ModuleNotFoundError: No module named 'src.survey.synthesizer'`.

- [ ] **Step 3: Implement synthesizer**

Create `src/survey/synthesizer.py`:

```python
from __future__ import annotations

import json
from typing import Any, Optional, Protocol, Sequence

from src.reader.staged_models import PaperReadingPackage
from src.survey.models import TopicProfile
from src.survey.synthesis_models import SurveySynthesis


class SurveySynthesisLLM(Protocol):
    async def generate_json(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        ...


class SurveySynthesizer:
    def __init__(self, llm: SurveySynthesisLLM, model: Optional[str]) -> None:
        self.llm = llm
        self.model = model

    async def synthesize(
        self,
        topic: TopicProfile,
        packages: Sequence[PaperReadingPackage],
    ) -> SurveySynthesis:
        if not packages:
            raise ValueError("At least one reading package is required for synthesis")
        prompt = _build_prompt(topic, packages)
        raw = await self.llm.generate_json(prompt, model=self.model, temperature=0.1)
        synthesis = SurveySynthesis.from_dict(raw)
        _validate_known_paper_ids(synthesis, {package.paper_id for package in packages})
        return synthesis


def _build_prompt(topic: TopicProfile, packages: Sequence[PaperReadingPackage]) -> str:
    topic_payload = {
        "topic_id": topic.topic_id,
        "name": topic.name,
        "description": topic.description,
        "intent": topic.intent,
        "concept_axes": [axis.__dict__ for axis in topic.concept_axes],
        "scope": topic.scope.__dict__,
        "anchor_papers": topic.anchor_papers,
        "benchmark_hints": topic.benchmark_hints,
        "open_questions": topic.open_questions,
    }
    reading_payload = [
        {
            "paper_id": package.paper_id,
            "title": package.title,
            "summary": package.summary.to_dict() if package.summary else None,
            "claims": [claim.to_dict() for claim in package.claims[:8]],
            "method_modules": [module.to_dict() for module in package.method_modules[:8]],
            "experiments": [record.to_dict() for record in package.experiments[:8]],
            "topic_relation": (
                package.topic_relation.to_dict() if package.topic_relation else None
            ),
            "critique": package.critique[:8],
            "follow_up_questions": package.follow_up_questions[:8],
        }
        for package in packages
    ]
    return "\n".join(
        [
            "You synthesize a research survey from staged paper readings.",
            "Use only the provided reading packages. Do not invent paper ids.",
            "",
            "## Topic",
            json.dumps(topic_payload, ensure_ascii=False, indent=2),
            "",
            "## Reading Packages",
            json.dumps(reading_payload, ensure_ascii=False, indent=2),
            "",
            "## Output Schema",
            (
                "Return JSON with keys taxonomy, paper_map, positioning, references, "
                "open_questions. paper_map.role must be one of core, adjacent, "
                "collision, background. Every paper_id must come from Reading Packages."
            ),
        ]
    )


def _validate_known_paper_ids(synthesis: SurveySynthesis, known_ids: set[str]) -> None:
    referenced_ids = set()
    for group in synthesis.taxonomy:
        referenced_ids.update(group.paper_ids)
    for item in synthesis.paper_map:
        referenced_ids.add(item.paper_id)
    for entry in synthesis.references:
        referenced_ids.add(entry.paper_id)
    unknown_ids = sorted(referenced_ids - known_ids)
    if unknown_ids:
        raise ValueError(f"Synthesis referenced unknown paper_id values: {unknown_ids}")
```

- [ ] **Step 4: Run synthesizer tests and verify GREEN**

Run:

```bash
python -m pytest tests/survey/test_synthesizer.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Commit**

Run:

```bash
git add src/survey/synthesizer.py tests/survey/test_synthesizer.py
git commit -m "feat: add survey synthesizer"
```

---

## Task 5: Survey Synthesize CLI

**Files:**
- Modify: `src/survey/cli.py`
- Modify: `run.py`
- Test: `tests/survey/test_cli.py`

- [ ] **Step 1: Add failing CLI tests**

Extend `tests/survey/test_cli.py` with these tests:

```python
from __future__ import annotations

import pytest

from run import build_parser


def test_survey_synthesize_requires_topic() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["survey", "synthesize"])


def test_survey_synthesize_accepts_topic_and_readings_dir() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "survey",
            "synthesize",
            "--topic",
            "data/topics/topic/topic.yaml",
            "--readings-dir",
            "data/readings",
        ]
    )

    assert args.command == "survey"
    assert args.survey_command == "synthesize"
    assert args.topic == "data/topics/topic/topic.yaml"
    assert args.readings_dir == "data/readings"
```

Also add a lazy import smoke test if one does not already exist:

```python
def test_survey_cli_import_is_lightweight() -> None:
    import src.survey.cli  # noqa: F401
```

- [ ] **Step 2: Run CLI tests and verify RED**

Run:

```bash
python -m pytest tests/survey/test_cli.py -q
```

Expected: new synthesize parser tests fail because `synthesize` is not registered.

- [ ] **Step 3: Wire parser in `run.py`**

Modify `run.py` in `build_parser()` after the `refine_parser` block:

```python
    synthesize_parser = survey_subparsers.add_parser(
        "synthesize",
        help="Synthesize survey artifacts from staged reading packages",
    )
    synthesize_parser.add_argument(
        "--topic",
        required=True,
        help="Path to topic.yaml",
    )
    synthesize_parser.add_argument(
        "--readings-dir",
        help="Directory containing staged reading package JSON files",
    )
```

No extra parser validation is required beyond `required=True`.

- [ ] **Step 4: Implement `cmd_survey_synthesize`**

Modify `src/survey/cli.py`:

```python
import yaml
```

Add helpers and command:

```python
async def cmd_survey_synthesize(args) -> None:
    try:
        from src.llm.gemini_client import GeminiClient
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name == "google" or exc.name.startswith("google.")):
            raise SystemExit(
                "Error: google-genai is required for survey synthesize. "
                "Run pip install -r requirements.txt."
            ) from exc
        raise

    load_dotenv()
    app_config = load_config(args.config)
    api_key = os.environ.get("GEMINI_API_KEY", "") or app_config.llm.api_key
    if not api_key:
        raise SystemExit("Error: GEMINI_API_KEY environment variable not set.")

    topic_path = Path(args.topic)
    topic = _load_topic(topic_path)
    topic_dir = topic_path.parent
    readings_dir = Path(args.readings_dir) if args.readings_dir else topic_dir / "papers"

    from src.survey.reading_loader import load_reading_packages
    from src.survey.survey_renderer import (
        render_paper_map_markdown,
        render_positioning_markdown,
        render_references_markdown,
        render_taxonomy_markdown,
    )
    from src.survey.synthesizer import SurveySynthesizer

    packages = load_reading_packages(readings_dir)
    llm_config = LLMConfig(
        filter_model=app_config.llm.filter_model,
        reader_model=app_config.llm.reader_model,
        embedding_model=app_config.llm.embedding_model,
        api_key=api_key,
        max_concurrent=app_config.llm.max_concurrent,
        temperature=app_config.llm.temperature,
    )
    synthesis = await SurveySynthesizer(
        GeminiClient(llm_config), model=llm_config.reader_model
    ).synthesize(topic, packages)

    manager = TopicArtifactManager(topic_dir.parent)
    manager.create_or_update_topic(topic)
    manager.update_auto_block(topic_dir / "survey.md", "taxonomy", render_taxonomy_markdown(synthesis))
    manager.update_auto_block(topic_dir / "papers.md", "paper-map", render_paper_map_markdown(synthesis))
    manager.update_auto_block(
        topic_dir / "positioning.md", "positioning", render_positioning_markdown(synthesis)
    )
    manager.update_auto_block(
        topic_dir / "references.md", "references", render_references_markdown(synthesis)
    )
    manager.append_event(
        topic_dir,
        SurveyEvent(
            event_type="synthesize",
            message=f"Synthesized survey from {len(packages)} reading packages.",
        ),
    )

    print(f"Survey: {topic_dir / 'survey.md'}")
    print(f"Papers: {topic_dir / 'papers.md'}")
    print(f"Positioning: {topic_dir / 'positioning.md'}")
    print(f"References: {topic_dir / 'references.md'}")
```

Add topic loader:

```python
def _load_topic(path: Path):
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Error loading topic YAML {path}: not found") from exc
    except yaml.YAMLError as exc:
        raise SystemExit(f"Error loading topic YAML {path}: invalid YAML: {exc}") from exc

    if raw is None:
        raise SystemExit(f"Error loading topic YAML {path}: empty YAML")
    if not isinstance(raw, dict):
        raise SystemExit(f"Error loading topic YAML {path}: expected mapping object")

    from src.survey.models import TopicProfile

    try:
        return TopicProfile.from_dict(raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(
            f"Error loading topic YAML {path}: malformed TopicProfile: {exc}"
        ) from exc
```

Update `run_survey_command`:

```python
    if args.survey_command == "synthesize":
        asyncio.run(cmd_survey_synthesize(args))
        return
```

- [ ] **Step 5: Run CLI tests and survey tests**

Run:

```bash
python -m pytest tests/survey/test_cli.py tests/survey -q
```

Expected: all survey tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add run.py src/survey/cli.py tests/survey/test_cli.py
git commit -m "feat: add survey synthesize CLI"
```

---

## Task 6: End-to-End Fake Synthesis Workflow

**Files:**
- Test: `tests/survey/test_synthesize_workflow.py`

- [ ] **Step 1: Write workflow test**

Create `tests/survey/test_synthesize_workflow.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from src.reader.staged_models import PaperReadingPackage, PaperSummary, TopicRelation
from src.survey.artifacts import TopicArtifactManager
from src.survey.models import ConceptAxis, TopicProfile, TopicScope
from src.survey.reading_loader import load_reading_packages
from src.survey.survey_renderer import (
    render_paper_map_markdown,
    render_positioning_markdown,
    render_references_markdown,
    render_taxonomy_markdown,
)
from src.survey.synthesizer import SurveySynthesizer


def _topic() -> TopicProfile:
    return TopicProfile(
        topic_id="utility_nav",
        name="Utility Navigation",
        description="Task-conditioned utility over 3D memory.",
        intent="Find a thesis gap.",
        concept_axes=[ConceptAxis(name="utility", description="Candidate scoring.")],
        scope=TopicScope(positive=["ObjectNav"], collision=["MTU3D"]),
    )


def _package(paper_id: str, title: str) -> PaperReadingPackage:
    return PaperReadingPackage(
        paper_id=paper_id,
        title=title,
        source_path=f"{paper_id}.pdf",
        summary=PaperSummary(
            problem="Navigation requires decisions.",
            method="Scores candidates.",
            takeaway=f"{title} is relevant.",
            contributions=["Candidate scoring"],
        ),
        topic_relation=TopicRelation(
            relevance="core",
            concept_axes=["utility"],
            collision_risk="medium",
            differentiation="Uses explicit scoring.",
        ),
    )


class FakeLLM:
    async def generate_json(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        return {
            "taxonomy": [
                {
                    "name": "Explicit utility models",
                    "description": "Score candidate actions.",
                    "paper_ids": ["mtu3d"],
                    "key_distinction": "Exposes decision scores.",
                }
            ],
            "paper_map": [
                {
                    "paper_id": "mtu3d",
                    "title": "MTU3D",
                    "role": "collision",
                    "rationale": "Closest overlap.",
                    "evidence": "Candidate scoring.",
                }
            ],
            "positioning": {
                "thesis_gap": "General utility over 3D memory.",
                "novelty_claim": "Beyond object/frontier scoring.",
                "collision_risks": ["MTU3D overlap."],
                "recommended_positioning": "Emphasize task-conditioned utility.",
            },
            "references": [
                {
                    "paper_id": "mtu3d",
                    "title": "MTU3D",
                    "why_relevant": "Collision paper.",
                    "evidence": "Candidate scoring.",
                }
            ],
            "open_questions": ["How is utility supervised?"],
        }


async def _run_workflow(topic_dir: Path) -> None:
    topic = _topic()
    manager = TopicArtifactManager(topic_dir.parent)
    paths = manager.create_or_update_topic(topic)
    package = _package("mtu3d", "MTU3D")
    (paths.topic_dir / "papers" / "mtu3d.json").write_text(
        json.dumps(package.to_dict()), encoding="utf-8"
    )
    (paths.topic_dir / "survey.md").write_text(
        "# Utility Navigation Survey\n\nManual note.\n\n"
        "<!-- BEGIN AUTO:taxonomy -->\nOld\n<!-- END AUTO:taxonomy -->\n",
        encoding="utf-8",
    )

    packages = load_reading_packages(paths.topic_dir / "papers")
    synthesis = await SurveySynthesizer(FakeLLM(), model="test-model").synthesize(
        topic, packages
    )
    manager.update_auto_block(
        paths.topic_dir / "survey.md", "taxonomy", render_taxonomy_markdown(synthesis)
    )
    manager.update_auto_block(
        paths.topic_dir / "papers.md", "paper-map", render_paper_map_markdown(synthesis)
    )
    manager.update_auto_block(
        paths.topic_dir / "positioning.md",
        "positioning",
        render_positioning_markdown(synthesis),
    )
    manager.update_auto_block(
        paths.topic_dir / "references.md",
        "references",
        render_references_markdown(synthesis),
    )


def test_fake_synthesize_workflow_updates_artifacts(tmp_path) -> None:
    import asyncio

    asyncio.run(_run_workflow(tmp_path / "utility_nav"))

    topic_dir = tmp_path / "utility_nav"
    survey = (topic_dir / "survey.md").read_text(encoding="utf-8")
    papers = (topic_dir / "papers.md").read_text(encoding="utf-8")
    positioning = (topic_dir / "positioning.md").read_text(encoding="utf-8")
    references = (topic_dir / "references.md").read_text(encoding="utf-8")

    assert "Manual note." in survey
    assert "Explicit utility models" in survey
    assert "Old" not in survey
    assert "MTU3D" in papers
    assert "General utility over 3D memory." in positioning
    assert "Collision paper." in references
```

- [ ] **Step 2: Run workflow test**

Run:

```bash
python -m pytest tests/survey/test_synthesize_workflow.py -q
```

Expected:

```text
1 passed
```

- [ ] **Step 3: Run survey tests**

Run:

```bash
python -m pytest tests/survey -q
```

Expected: all survey tests pass.

- [ ] **Step 4: Commit**

Run:

```bash
git add tests/survey/test_synthesize_workflow.py
git commit -m "test: cover survey synthesize workflow"
```

---

## Task 7: Manual Real-Paper Smoke

**Files:**
- No tracked code changes expected.

- [ ] **Step 1: Confirm local PDF corpus**

Run:

```powershell
Get-ChildItem data/pdfs/mvp3-smoke/*.pdf | Select-Object Name,Length
```

Expected: at least `mtu3d.pdf`, `msgnav.pdf`, `vlfm.pdf`.

- [ ] **Step 2: Generate staged reading packages for three PDFs**

Use the existing smoke topic:

```powershell
$topic = "data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/topic.yaml"
$env:GEMINI_API_KEY = ((Get-Content -Path 'C:\DiskD\git\paper_reader\.env' | Where-Object { $_ -match '^GEMINI_API_KEY=' } | Select-Object -First 1) -replace '^GEMINI_API_KEY=', '').Trim()
python run.py read --staged --pdf data/pdfs/mvp3-smoke/mtu3d.pdf --paper-id mtu3d --title "Move to Understand a 3D Scene" --topic $topic
python run.py read --staged --pdf data/pdfs/mvp3-smoke/msgnav.pdf --paper-id msgnav --title "MSGNav: Unleashing the Power of Multi-modal 3D Scene Graph for Zero-Shot Embodied Navigation" --topic $topic
python run.py read --staged --pdf data/pdfs/mvp3-smoke/vlfm.pdf --paper-id vlfm --title "VLFM: Vision-Language Frontier Maps for Zero-Shot Semantic Navigation" --topic $topic
```

Expected: JSON and Markdown reading packages appear under the topic's `papers/` directory.

- [ ] **Step 3: Run real survey synthesis smoke**

Run:

```powershell
python run.py survey synthesize --topic $topic
```

Expected output includes:

```text
Survey:
Papers:
Positioning:
References:
```

- [ ] **Step 4: Inspect generated artifacts**

Run:

```powershell
Get-Content data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/survey.md -TotalCount 120
Get-Content data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/papers.md -TotalCount 160
Get-Content data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/positioning.md -TotalCount 160
```

Expected: auto-blocks contain synthesized content and existing manual text outside auto-blocks remains.

- [ ] **Step 5: Confirm generated data is ignored**

Run:

```bash
git status --short
```

Expected: no tracked changes from `data/`.

---

## Task 8: Final Verification And PR Update

**Files:**
- No tracked code changes expected unless fixes are required.

- [ ] **Step 1: Run full tests**

Run:

```bash
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run compile check**

Run:

```bash
python -m compileall src run.py
```

Expected: exits 0.

- [ ] **Step 3: Check lightweight imports**

Run:

```bash
python -c "import src.survey.cli"
python -c "import src.reader.staged_cli"
```

Expected: both exit 0 without requiring `google-genai` at import time.

- [ ] **Step 4: Check git status**

Run:

```bash
git status --short --branch
```

Expected: tracked files are clean. Ignored `data/` smoke artifacts may exist but should not appear.

- [ ] **Step 5: Request final code review**

Dispatch a reviewer with:

- base SHA: commit before Task 1 implementation;
- head SHA: current HEAD;
- requirements: this plan plus `docs/superpowers/specs/2026-05-15-mvp3-survey-synthesis-design.md`.

Fix Critical and Important issues before proceeding.

- [ ] **Step 6: Push branch and update PR**

Run:

```bash
git push origin mvp1-topic-refinement
```

Then add a PR comment summarizing:

- implemented `survey synthesize`;
- tests and compile results;
- real smoke result;
- deferred paper search/SOTA scope.
