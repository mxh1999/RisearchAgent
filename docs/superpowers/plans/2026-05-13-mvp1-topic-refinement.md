# MVP-1 Topic Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `survey refine` so a vague research direction or prior chat note becomes a stable topic profile and a reusable topic artifact directory.

**Architecture:** Add a new `src/survey/` package with focused units: topic data models, artifact updates, LLM-backed topic refinement, and CLI wiring. The first version creates and updates stable files under topic-specific directories such as `data/topics/decision_aware_3d_navigation/` and appends structured survey events, without implementing paper collection or full survey synthesis yet.

**Tech Stack:** Python dataclasses, PyYAML, JSONL, argparse, existing `GeminiClient`, pytest for tests.

---

## Scope

This plan implements MVP-1 only:

- `python run.py survey refine "topic description"`
- `python run.py survey refine --from-note path/to/note.md`
- topic profile serialization to `topic.yaml`
- stable artifact creation and auto-block updating
- `state/survey_events.jsonl`
- tests for topic IDs, YAML round-trip, artifact preservation, and CLI argument behavior

This plan intentionally does not implement:

- paper search;
- paper reading;
- survey synthesis over multiple papers;
- structured SOTA storage.

Those are MVP-2, MVP-3, and MVP-4.

## File Structure

- Create `src/survey/__init__.py`: package marker and public exports.
- Create `src/survey/models.py`: dataclasses for `TopicProfile`, `ConceptAxis`, `TopicScope`, `TopicQuery`, and `SurveyEvent`.
- Create `src/survey/artifacts.py`: `TopicArtifactManager` for topic directories, stable Markdown files, auto-block replacement, YAML writes, and event appends.
- Create `src/survey/refiner.py`: `TopicRefiner` with prompt construction, JSON parsing, fallback topic ID generation, and note/direct-input entry points.
- Create `src/survey/cli.py`: command handlers for `survey refine`.
- Modify `run.py`: add `survey` subcommands and route to `src.survey.cli`.
- Modify `requirements.txt`: add `pytest>=8.0.0` for the new tests.
- Create `tests/survey/test_models.py`: model serialization and topic ID tests.
- Create `tests/survey/test_artifacts.py`: stable file creation and auto-block preservation tests.
- Create `tests/survey/test_refiner.py`: LLM response parsing using a fake LLM client.
- Create `tests/survey/test_cli.py`: argparse integration test for `survey refine`.

## Task 1: Test Infrastructure

**Files:**
- Modify: `requirements.txt`
- Create: `tests/survey/__init__.py`

- [ ] **Step 1: Add pytest dependency**

Add this line to `requirements.txt`:

```text
pytest>=8.0.0
```

- [ ] **Step 2: Create test package marker**

Create `tests/survey/__init__.py` as an empty file.

- [ ] **Step 3: Run current tests**

Run:

```bash
pytest -q
```

Expected before installing dependencies in a fresh environment:

```text
ModuleNotFoundError: No module named 'pytest'
```

Expected after `pip install -r requirements.txt`:

```text
no tests ran
```

- [ ] **Step 4: Commit**

```bash
git add requirements.txt tests/survey/__init__.py
git commit -m "test: add pytest test scaffold"
```

## Task 2: Topic Data Models

**Files:**
- Create: `src/survey/__init__.py`
- Create: `src/survey/models.py`
- Test: `tests/survey/test_models.py`

- [ ] **Step 1: Write failing model tests**

Create `tests/survey/test_models.py`:

```python
from src.survey.models import (
    ConceptAxis,
    TopicProfile,
    TopicQuery,
    TopicScope,
    make_topic_id,
)


def test_make_topic_id_normalizes_research_title() -> None:
    topic_id = make_topic_id("Task-conditioned 3D Utility Learning for Navigation!")
    assert topic_id == "task_conditioned_3d_utility_learning_for_navigation"


def test_topic_profile_round_trip_dict() -> None:
    profile = TopicProfile(
        topic_id="decision_aware_3d_nav",
        name="Decision-Aware 3D Navigation",
        description="Study how 3D memory becomes navigation decisions.",
        intent="Find papers about task-conditioned utility over 3D memories.",
        concept_axes=[
            ConceptAxis(
                name="task_conditioned_utility",
                description="Scores objects, frontiers, regions, or viewpoints.",
            )
        ],
        scope=TopicScope(
            positive=["3D memory for embodied navigation"],
            negative=["pure SLAM without semantic decisions"],
            adjacent=["static 3D grounding"],
            collision=["MSGNav"],
        ),
        anchor_papers=["MTU3D"],
        benchmark_hints=["GOAT-Bench"],
        search_queries=[
            TopicQuery(
                name="direct",
                query='"embodied navigation" "3D memory"',
                purpose="Find direct matches.",
            )
        ],
        open_questions=["What utility supervision is available?"],
    )

    restored = TopicProfile.from_dict(profile.to_dict())

    assert restored == profile
    assert restored.search_queries[0].query == '"embodied navigation" "3D memory"'
```

- [ ] **Step 2: Run model tests and verify failure**

Run:

```bash
pytest tests/survey/test_models.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'src.survey'
```

- [ ] **Step 3: Implement survey models**

Create `src/survey/__init__.py`:

```python
"""Survey workflows for topic refinement and research artifacts."""

from src.survey.models import (
    ConceptAxis,
    SurveyEvent,
    TopicProfile,
    TopicQuery,
    TopicScope,
    make_topic_id,
)

__all__ = [
    "ConceptAxis",
    "SurveyEvent",
    "TopicProfile",
    "TopicQuery",
    "TopicScope",
    "make_topic_id",
]
```

Create `src/survey/models.py`:

```python
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def make_topic_id(name: str, max_length: int = 72) -> str:
    """Create a stable filesystem-safe topic id from a topic name."""
    normalized = name.lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        normalized = "untitled_topic"
    return normalized[:max_length].rstrip("_")


@dataclass(frozen=True)
class ConceptAxis:
    name: str
    description: str


@dataclass(frozen=True)
class TopicScope:
    positive: list[str] = field(default_factory=list)
    negative: list[str] = field(default_factory=list)
    adjacent: list[str] = field(default_factory=list)
    collision: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TopicQuery:
    name: str
    query: str
    purpose: str


@dataclass(frozen=True)
class TopicProfile:
    topic_id: str
    name: str
    description: str
    intent: str
    concept_axes: list[ConceptAxis] = field(default_factory=list)
    scope: TopicScope = field(default_factory=TopicScope)
    anchor_papers: list[str] = field(default_factory=list)
    benchmark_hints: list[str] = field(default_factory=list)
    search_queries: list[TopicQuery] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TopicProfile":
        axes = [ConceptAxis(**item) for item in raw.get("concept_axes", [])]
        scope = TopicScope(**raw.get("scope", {}))
        queries = [TopicQuery(**item) for item in raw.get("search_queries", [])]
        return cls(
            topic_id=raw["topic_id"],
            name=raw["name"],
            description=raw["description"],
            intent=raw["intent"],
            concept_axes=axes,
            scope=scope,
            anchor_papers=list(raw.get("anchor_papers", [])),
            benchmark_hints=list(raw.get("benchmark_hints", [])),
            search_queries=queries,
            open_questions=list(raw.get("open_questions", [])),
        )


@dataclass(frozen=True)
class SurveyEvent:
    event_type: str
    message: str
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, str]:
        return asdict(self)
```

- [ ] **Step 4: Run model tests and verify pass**

Run:

```bash
pytest tests/survey/test_models.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit**

```bash
git add src/survey/__init__.py src/survey/models.py tests/survey/test_models.py
git commit -m "feat: add survey topic models"
```

## Task 3: Topic Artifact Manager

**Files:**
- Create: `src/survey/artifacts.py`
- Test: `tests/survey/test_artifacts.py`

- [ ] **Step 1: Write failing artifact tests**

Create `tests/survey/test_artifacts.py`:

```python
import json

import yaml

from src.survey.artifacts import TopicArtifactManager
from src.survey.models import ConceptAxis, SurveyEvent, TopicProfile, TopicScope


def make_profile() -> TopicProfile:
    return TopicProfile(
        topic_id="decision_aware_3d_nav",
        name="Decision-Aware 3D Navigation",
        description="Study how 3D memory becomes navigation decisions.",
        intent="Find papers about task-conditioned utility over 3D memories.",
        concept_axes=[
            ConceptAxis(
                name="task_conditioned_utility",
                description="Scores object, frontier, region, or viewpoint candidates.",
            )
        ],
        scope=TopicScope(
            positive=["3D memory for embodied navigation"],
            negative=["pure SLAM without semantic decisions"],
        ),
    )


def test_create_topic_artifacts_writes_stable_files(tmp_path) -> None:
    manager = TopicArtifactManager(tmp_path)
    paths = manager.create_or_update_topic(make_profile())

    assert paths.topic_dir == tmp_path / "decision_aware_3d_nav"
    assert paths.topic_yaml.exists()
    assert (paths.topic_dir / "survey.md").exists()
    assert (paths.topic_dir / "papers.md").exists()
    assert (paths.topic_dir / "references.md").exists()
    assert (paths.topic_dir / "positioning.md").exists()
    assert (paths.topic_dir / "state" / "survey_events.jsonl").exists()

    raw = yaml.safe_load(paths.topic_yaml.read_text(encoding="utf-8"))
    assert raw["topic_id"] == "decision_aware_3d_nav"
    assert raw["concept_axes"][0]["name"] == "task_conditioned_utility"


def test_update_auto_block_preserves_manual_text(tmp_path) -> None:
    manager = TopicArtifactManager(tmp_path)
    paths = manager.create_or_update_topic(make_profile())
    survey_path = paths.topic_dir / "survey.md"
    survey_path.write_text(
        "# Survey\n\nManual note.\n\n"
        "<!-- BEGIN AUTO:taxonomy -->\nOld taxonomy\n<!-- END AUTO:taxonomy -->\n",
        encoding="utf-8",
    )

    manager.update_auto_block(
        survey_path,
        "taxonomy",
        "## Taxonomy\n\n- Task-conditioned utility\n",
    )

    content = survey_path.read_text(encoding="utf-8")
    assert "Manual note." in content
    assert "Old taxonomy" not in content
    assert "- Task-conditioned utility" in content


def test_append_event_writes_jsonl(tmp_path) -> None:
    manager = TopicArtifactManager(tmp_path)
    paths = manager.create_or_update_topic(make_profile())

    manager.append_event(
        paths.topic_dir,
        SurveyEvent(event_type="refine", message="Created topic profile."),
    )

    lines = (paths.topic_dir / "state" / "survey_events.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event_type"] == "refine"
```

- [ ] **Step 2: Run artifact tests and verify failure**

Run:

```bash
pytest tests/survey/test_artifacts.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'src.survey.artifacts'
```

- [ ] **Step 3: Implement artifact manager**

Create `src/survey/artifacts.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

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

        if begin in text and end in text:
            before = text.split(begin, 1)[0]
            after = text.split(end, 1)[1]
            updated = before + replacement + after
        else:
            updated = text.rstrip() + "\n\n" + replacement + "\n"

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
```

- [ ] **Step 4: Run artifact tests and verify pass**

Run:

```bash
pytest tests/survey/test_artifacts.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Commit**

```bash
git add src/survey/artifacts.py tests/survey/test_artifacts.py
git commit -m "feat: add topic artifact manager"
```

## Task 4: LLM Topic Refiner

**Files:**
- Create: `src/survey/refiner.py`
- Test: `tests/survey/test_refiner.py`

- [ ] **Step 1: Write failing refiner tests**

Create `tests/survey/test_refiner.py`:

```python
import pytest

from src.survey.refiner import TopicRefiner


class FakeLLM:
    async def generate_json(self, prompt: str, *, model: str | None = None, temperature: float | None = None):
        assert "Topic Refinement Task" in prompt
        return {
            "name": "Decision-Aware 3D Navigation",
            "description": "Study how 3D memory becomes navigation decisions.",
            "intent": "Find papers about task-conditioned utility over 3D memories.",
            "concept_axes": [
                {
                    "name": "task_conditioned_utility",
                    "description": "Scores object, frontier, region, or viewpoint candidates.",
                }
            ],
            "scope": {
                "positive": ["3D memory for embodied navigation"],
                "negative": ["pure SLAM without semantic decisions"],
                "adjacent": ["static 3D grounding"],
                "collision": ["MSGNav"],
            },
            "anchor_papers": ["MTU3D"],
            "benchmark_hints": ["GOAT-Bench"],
            "search_queries": [
                {
                    "name": "direct",
                    "query": '"embodied navigation" "3D memory"',
                    "purpose": "Find direct matches.",
                }
            ],
            "open_questions": ["What utility supervision is available?"],
        }


@pytest.mark.asyncio
async def test_refine_text_builds_topic_profile() -> None:
    refiner = TopicRefiner(llm=FakeLLM(), model="gemini-2.5-pro")
    profile = await refiner.refine_text(
        "I want papers about 3D understanding for embodied navigation decisions."
    )

    assert profile.topic_id == "decision_aware_3d_navigation"
    assert profile.scope.collision == ["MSGNav"]
    assert profile.search_queries[0].name == "direct"


@pytest.mark.asyncio
async def test_refine_note_includes_note_path(tmp_path) -> None:
    note_path = tmp_path / "brainstorm.md"
    note_path.write_text("# Brainstorm\n\nMTU3D and MSGNav are relevant.", encoding="utf-8")

    refiner = TopicRefiner(llm=FakeLLM(), model="gemini-2.5-pro")
    profile = await refiner.refine_note(note_path)

    assert profile.name == "Decision-Aware 3D Navigation"
```

- [ ] **Step 2: Add pytest-asyncio dependency**

Add this line to `requirements.txt`:

```text
pytest-asyncio>=0.23.0
```

- [ ] **Step 3: Run refiner tests and verify failure**

Run:

```bash
pytest tests/survey/test_refiner.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'src.survey.refiner'
```

- [ ] **Step 4: Implement topic refiner**

Create `src/survey/refiner.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from src.survey.models import (
    ConceptAxis,
    TopicProfile,
    TopicQuery,
    TopicScope,
    make_topic_id,
)


class TopicRefinerLLM(Protocol):
    async def generate_json(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float | None = None,
    ) -> Any:
        pass


REFINE_PROMPT = """You are a senior research advisor helping define a survey topic.

## Topic Refinement Task

Input source: {source}

User material:
{material}

Return JSON with exactly these fields:
{{
  "name": "short topic title",
  "description": "2-4 sentence topic description",
  "intent": "what the user is trying to understand or build",
  "concept_axes": [
    {{"name": "snake_case_axis", "description": "what this axis means"}}
  ],
  "scope": {{
    "positive": ["paper types that should be included"],
    "negative": ["paper types that should be excluded"],
    "adjacent": ["related but non-core paper types"],
    "collision": ["papers or directions that may threaten novelty"]
  }},
  "anchor_papers": ["paper names or ids"],
  "benchmark_hints": ["benchmarks or datasets"],
  "search_queries": [
    {{"name": "query_family_name", "query": "search query", "purpose": "why this query exists"}}
  ],
  "open_questions": ["questions to resolve during survey"]
}}

Rules:
- Do not assume the topic is a classic field with a single established name.
- Use positive and negative scope to protect cross-disciplinary topics from query drift.
- Include collision papers when the material mentions close overlap or novelty risk.
- Generate multiple query families when the direction is emerging.
"""


class TopicRefiner:
    """Convert vague research material into a structured topic profile."""

    def __init__(self, llm: TopicRefinerLLM, model: str):
        self.llm = llm
        self.model = model

    async def refine_text(self, text: str) -> TopicProfile:
        return await self._refine(source="direct input", material=text)

    async def refine_note(self, note_path: Path) -> TopicProfile:
        material = note_path.read_text(encoding="utf-8")
        return await self._refine(source=str(note_path), material=material)

    async def _refine(self, source: str, material: str) -> TopicProfile:
        prompt = REFINE_PROMPT.format(source=source, material=material)
        raw = await self.llm.generate_json(
            prompt,
            model=self.model,
            temperature=0.2,
        )
        return self._profile_from_llm(raw)

    @staticmethod
    def _profile_from_llm(raw: dict[str, Any]) -> TopicProfile:
        name = str(raw["name"]).strip()
        axes = [
            ConceptAxis(
                name=str(item["name"]).strip(),
                description=str(item["description"]).strip(),
            )
            for item in raw.get("concept_axes", [])
        ]
        scope_raw = raw.get("scope", {})
        scope = TopicScope(
            positive=list(scope_raw.get("positive", [])),
            negative=list(scope_raw.get("negative", [])),
            adjacent=list(scope_raw.get("adjacent", [])),
            collision=list(scope_raw.get("collision", [])),
        )
        queries = [
            TopicQuery(
                name=str(item["name"]).strip(),
                query=str(item["query"]).strip(),
                purpose=str(item["purpose"]).strip(),
            )
            for item in raw.get("search_queries", [])
        ]
        return TopicProfile(
            topic_id=make_topic_id(name),
            name=name,
            description=str(raw["description"]).strip(),
            intent=str(raw["intent"]).strip(),
            concept_axes=axes,
            scope=scope,
            anchor_papers=list(raw.get("anchor_papers", [])),
            benchmark_hints=list(raw.get("benchmark_hints", [])),
            search_queries=queries,
            open_questions=list(raw.get("open_questions", [])),
        )
```

- [ ] **Step 5: Run refiner tests and verify pass**

Run:

```bash
pytest tests/survey/test_refiner.py -q
```

Expected:

```text
2 passed
```

- [ ] **Step 6: Commit**

```bash
git add requirements.txt src/survey/refiner.py tests/survey/test_refiner.py
git commit -m "feat: add LLM topic refiner"
```

## Task 5: Survey Refine CLI Handler

**Files:**
- Create: `src/survey/cli.py`
- Modify: `run.py`
- Test: `tests/survey/test_cli.py`

- [ ] **Step 1: Write failing CLI test**

Create `tests/survey/test_cli.py`:

```python
import argparse

from run import build_parser


def test_survey_refine_from_note_args() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "survey",
            "refine",
            "--from-note",
            "2026-05-11_21-32-21_thesis_direction_brainstorm.md",
        ]
    )

    assert args.command == "survey"
    assert args.survey_command == "refine"
    assert args.from_note == "2026-05-11_21-32-21_thesis_direction_brainstorm.md"
    assert args.topic_text is None


def test_survey_refine_text_args() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "survey",
            "refine",
            "task-conditioned 3D utility learning",
        ]
    )

    assert args.command == "survey"
    assert args.survey_command == "refine"
    assert args.topic_text == "task-conditioned 3D utility learning"


def test_survey_refine_rejects_missing_input() -> None:
    parser = build_parser()
    try:
        parser.parse_args(["survey", "refine"])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("parser should reject missing refine input")
```

- [ ] **Step 2: Run CLI test and verify failure**

Run:

```bash
pytest tests/survey/test_cli.py -q
```

Expected:

```text
ImportError: cannot import name 'build_parser' from 'run'
```

- [ ] **Step 3: Extract parser builder in `run.py`**

In `run.py`, add this function above `main()`:

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="RisearchAgent - ArXiv paper analysis pipeline"
    )
    parser.add_argument(
        "-c", "--config", default="config.yaml", help="Config file path"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    subparsers.add_parser("crawl", help="Crawl ArXiv papers")
    subparsers.add_parser("filter", help="Filter papers by relevance")

    read_parser = subparsers.add_parser("read", help="Deep-read a specific paper")
    read_parser.add_argument("arxiv_id", help="ArXiv paper ID (e.g. 2401.12345)")

    subparsers.add_parser("pipeline", help="Run full 5-stage pipeline")
    subparsers.add_parser("sota", help="Show SOTA tracking table")
    subparsers.add_parser("stats", help="Show database statistics")

    export_parser = subparsers.add_parser("export", help="Export knowledge data to JSON")
    export_parser.add_argument(
        "output", nargs="?", default="knowledge_export.json",
        help="Output file path (default: knowledge_export.json)",
    )

    import_parser = subparsers.add_parser("import", help="Import knowledge data from JSON")
    import_parser.add_argument("input", help="Input JSON file path")
    import_parser.add_argument(
        "--merge", action="store_true",
        help="Merge with existing data (upsert) instead of replacing",
    )

    onboard_parser = subparsers.add_parser(
        "onboard", help="Interactive onboarding: set up research profile"
    )
    onboard_parser.add_argument(
        "--refine", action="store_true",
        help="Refine existing profile instead of starting fresh",
    )

    survey_parser = subparsers.add_parser("survey", help="Survey workflows")
    survey_subparsers = survey_parser.add_subparsers(
        dest="survey_command", required=True
    )
    refine_parser = survey_subparsers.add_parser(
        "refine", help="Refine a vague research direction into a topic profile"
    )
    refine_input = refine_parser.add_mutually_exclusive_group(required=True)
    refine_input.add_argument(
        "topic_text",
        nargs="?",
        help="Natural-language topic description",
    )
    refine_input.add_argument(
        "--from-note",
        help="Path to a prior chat note or brainstorming markdown file",
    )
    refine_parser.add_argument(
        "--topics-root",
        default="data/topics",
        help="Directory for topic artifacts",
    )

    return parser
```

Then change the start of `main()` to:

```python
def main():
    parser = build_parser()
    args = parser.parse_args()
    setup_logging(args.verbose)
```

Remove the duplicated parser construction from `main()`.

- [ ] **Step 4: Create CLI handler**

Create `src/survey/cli.py`:

```python
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from src.config import LLMConfig, load_config
from src.llm.gemini_client import GeminiClient
from src.survey.artifacts import TopicArtifactManager
from src.survey.models import SurveyEvent
from src.survey.refiner import TopicRefiner


async def cmd_survey_refine(args) -> None:
    """Run topic refinement and write stable topic artifacts."""
    load_dotenv()
    app_config = load_config(args.config)
    api_key = os.environ.get("GEMINI_API_KEY", app_config.llm.api_key)
    if not api_key:
        raise SystemExit("Error: GEMINI_API_KEY environment variable not set.")

    llm_config = LLMConfig(
        filter_model=app_config.llm.filter_model,
        reader_model=app_config.llm.reader_model,
        embedding_model=app_config.llm.embedding_model,
        api_key=api_key,
        max_concurrent=app_config.llm.max_concurrent,
        temperature=app_config.llm.temperature,
    )
    llm = GeminiClient(llm_config)
    refiner = TopicRefiner(llm=llm, model=llm_config.reader_model)

    if args.from_note:
        profile = await refiner.refine_note(Path(args.from_note))
        source = args.from_note
    else:
        profile = await refiner.refine_text(args.topic_text)
        source = "direct input"

    manager = TopicArtifactManager(Path(args.topics_root))
    paths = manager.create_or_update_topic(profile)
    manager.append_event(
        paths.topic_dir,
        SurveyEvent(
            event_type="refine",
            message=f"Refined topic profile from {source}.",
        ),
    )

    print(f"Topic profile written: {paths.topic_yaml}")
    print(f"Topic artifacts directory: {paths.topic_dir}")


def run_survey_command(args) -> None:
    if args.survey_command == "refine":
        asyncio.run(cmd_survey_refine(args))
        return
    raise SystemExit(f"Unknown survey command: {args.survey_command}")
```

- [ ] **Step 5: Route survey command in `run.py`**

In `run.py`, add this branch before loading regular pipeline config:

```python
    if args.command == "survey":
        from src.survey.cli import run_survey_command

        run_survey_command(args)
        return
```

Keep the existing `onboard` branch before this branch or after it; both should return before `config = load_config(args.config)` for non-pipeline commands.

- [ ] **Step 6: Run CLI tests and verify pass**

Run:

```bash
pytest tests/survey/test_cli.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 7: Commit**

```bash
git add run.py src/survey/cli.py tests/survey/test_cli.py
git commit -m "feat: add survey refine CLI"
```

## Task 6: End-to-End Refinement With Fake LLM

**Files:**
- Test: `tests/survey/test_refine_workflow.py`

- [ ] **Step 1: Write workflow test**

Create `tests/survey/test_refine_workflow.py`:

```python
import json

import pytest
import yaml

from src.survey.artifacts import TopicArtifactManager
from src.survey.models import SurveyEvent
from src.survey.refiner import TopicRefiner


class FakeLLM:
    async def generate_json(self, prompt: str, *, model: str | None = None, temperature: float | None = None):
        return {
            "name": "Decision-Aware 3D Navigation",
            "description": "Study how 3D memory becomes navigation decisions.",
            "intent": "Find papers about task-conditioned utility over 3D memories.",
            "concept_axes": [
                {
                    "name": "task_conditioned_utility",
                    "description": "Scores object, frontier, region, or viewpoint candidates.",
                }
            ],
            "scope": {
                "positive": ["3D memory for embodied navigation"],
                "negative": ["pure SLAM without semantic decisions"],
                "adjacent": ["static 3D grounding"],
                "collision": ["MSGNav"],
            },
            "anchor_papers": ["MTU3D", "MSGNav"],
            "benchmark_hints": ["GOAT-Bench"],
            "search_queries": [
                {
                    "name": "direct",
                    "query": '"embodied navigation" "3D memory"',
                    "purpose": "Find direct matches.",
                }
            ],
            "open_questions": ["What utility supervision is available?"],
        }


@pytest.mark.asyncio
async def test_refine_note_creates_topic_directory(tmp_path) -> None:
    note_path = tmp_path / "brainstorm.md"
    note_path.write_text(
        "We should focus on task-conditioned utility learning rather than RGB-only navigation.",
        encoding="utf-8",
    )
    topics_root = tmp_path / "topics"
    refiner = TopicRefiner(llm=FakeLLM(), model="gemini-2.5-pro")
    manager = TopicArtifactManager(topics_root)

    profile = await refiner.refine_note(note_path)
    paths = manager.create_or_update_topic(profile)
    manager.append_event(
        paths.topic_dir,
        SurveyEvent(event_type="refine", message=f"Refined topic profile from {note_path}."),
    )

    topic_yaml = yaml.safe_load(paths.topic_yaml.read_text(encoding="utf-8"))
    event_lines = (paths.topic_dir / "state" / "survey_events.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()

    assert topic_yaml["topic_id"] == "decision_aware_3d_navigation"
    assert (paths.topic_dir / "survey.md").exists()
    assert json.loads(event_lines[0])["message"].startswith("Refined topic profile")
```

- [ ] **Step 2: Run workflow test and verify pass**

Run:

```bash
pytest tests/survey/test_refine_workflow.py -q
```

Expected:

```text
1 passed
```

- [ ] **Step 3: Run all survey tests**

Run:

```bash
pytest tests/survey -q
```

Expected:

```text
11 passed
```

- [ ] **Step 4: Commit**

```bash
git add tests/survey/test_refine_workflow.py
git commit -m "test: cover topic refinement workflow"
```

## Task 7: Manual CLI Smoke Test

**Files:**
- No code changes expected.

- [ ] **Step 1: Install dependencies if needed**

Run:

```bash
pip install -r requirements.txt
```

Expected:

```text
Successfully installed
```

The exact package list can vary by environment.

- [ ] **Step 2: Verify help output includes survey**

Run:

```bash
python run.py --help
```

Expected output contains:

```text
survey
```

- [ ] **Step 3: Verify refine help output**

Run:

```bash
python run.py survey refine --help
```

Expected output contains:

```text
--from-note
--topics-root
```

- [ ] **Step 4: Run real refinement from the existing brainstorm note**

Run:

```bash
python run.py survey refine --from-note 2026-05-11_21-32-21_thesis_direction_brainstorm.md
```

Expected output:

```text
Topic profile written: data/topics/decision_aware_3d_navigation/topic.yaml
Topic artifacts directory: data/topics/decision_aware_3d_navigation
```

If the LLM generates a different title, verify that the printed paths use the snake_case topic id derived from that title.

- [ ] **Step 5: Inspect generated files**

Run:

```bash
Get-ChildItem -Recurse data/topics
```

Expected files include:

```text
topic.yaml
survey.md
papers.md
references.md
positioning.md
state/survey_events.jsonl
```

- [ ] **Step 6: Commit generated topic artifacts only if the user wants them versioned**

Default action: do not commit `data/topics/` because project data directories are gitignored and topic artifacts are user data.

## Task 8: Final Verification

**Files:**
- No code changes expected.

- [ ] **Step 1: Run all tests**

Run:

```bash
pytest -q
```

Expected:

```text
11 passed
```

- [ ] **Step 2: Run compile check**

Run:

```bash
python -m compileall src run.py
```

Expected:

```text
Compiling
```

The command exits with status 0.

- [ ] **Step 3: Check git status**

Run:

```bash
git status --short
```

Expected tracked changes are committed. Untracked user files such as the brainstorm markdown may remain untracked.

- [ ] **Step 4: Final commit if verification changed tracked files**

If Step 3 shows tracked changes from implementation tasks, commit them:

```bash
git add requirements.txt run.py src/survey tests/survey
git commit -m "chore: verify MVP-1 topic refinement"
```

Do not add `data/topics/` or the brainstorm markdown unless the user explicitly asks.

## Self-Review

Spec coverage:

- Topic refinement is covered by Tasks 2, 4, 5, and 6.
- Stable artifact creation and updating is covered by Task 3.
- `survey_events.jsonl` is covered by Tasks 3 and 6.
- CLI commands for `survey refine` and `--from-note` are covered by Task 5.
- Preservation of user-written Markdown is covered by Task 3.

Known deferred work:

- Paper search belongs to MVP-3.
- Paper reading belongs to MVP-2.
- SOTA storage belongs to MVP-4.
- Multi-turn interactive confirmation can be added after the single-command refinement path works.
