# MVP-7 Topic Discover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `python run.py topic discover --topic ...`, an arXiv-only discovery workflow that writes reviewable topic candidate artifacts without downloading, reading, or updating topic artifacts.

**Architecture:** Add `src/survey/topic_discover.py` as the pure service layer for candidate models, deduplication, existing-paper filtering, rendering, and artifact writes. Add `src/survey/arxiv_provider.py` as the only network-facing provider. Add `src/survey/discover_cli.py` and wire it through existing `topic` subcommands.

**Tech Stack:** Python dataclasses, pathlib, datetime, PyYAML, arxiv package, pytest, existing topic loading helpers.

---

## File Structure

- Create `src/survey/topic_discover.py`
  - `RawDiscoveryPaper`, `DiscoveryCandidate`, `DiscoveryReport`
  - `build_discovery_report(...)`
  - `render_discovery_markdown(...)`
  - `render_discovery_manifest_draft(...)`
  - `write_discovery_artifacts(...)`
- Create `src/survey/arxiv_provider.py`
  - `ArxivDiscoveryProvider`
  - conversion from arXiv package results to `RawDiscoveryPaper`
- Create `src/survey/discover_cli.py`
  - `cmd_topic_discover(args, provider=None)`
  - preflight validation and console output
- Modify `src/survey/topic_cli.py`
  - dispatch `topic discover`
- Modify `run.py`
  - parse `topic discover` arguments
- Create `tests/survey/test_topic_discover.py`
  - service, rendering, CLI, provider-boundary tests

---

### Task 1: Discovery Models, Deduplication, And Renderers

**Files:**
- Create: `src/survey/topic_discover.py`
- Test: `tests/survey/test_topic_discover.py`

- [ ] **Step 1: Write failing service tests**

Create `tests/survey/test_topic_discover.py`:

```python
from __future__ import annotations

import json
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.survey.models import TopicProfile, TopicQuery
from src.survey.topic_discover import (
    RawDiscoveryPaper,
    build_discovery_report,
    render_discovery_manifest_draft,
    render_discovery_markdown,
    write_discovery_artifacts,
)


def _topic() -> TopicProfile:
    return TopicProfile(
        topic_id="utility_nav",
        name="Utility Navigation",
        description="Task-conditioned utility over 3D memory.",
        intent="Find candidate papers.",
        search_queries=[
            TopicQuery(name="direct", query='"utility" "navigation"', purpose="Direct topic query."),
            TopicQuery(name="benchmark", query='"GOAT-Bench" navigation', purpose="Benchmark query."),
        ],
    )


def _paper(
    arxiv_id: str,
    title: str,
    query_name: str,
    published: str = "2024-01-02T00:00:00+00:00",
) -> RawDiscoveryPaper:
    return RawDiscoveryPaper(
        arxiv_id=arxiv_id,
        title=title,
        abstract="This paper studies utility for embodied navigation. " * 4,
        authors=["A. Researcher", "B. Researcher"],
        published=datetime.fromisoformat(published),
        categories=["cs.RO", "cs.CV"],
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
        source_url=f"https://arxiv.org/abs/{arxiv_id}",
        query_name=query_name,
        query_purpose=f"{query_name} purpose",
    )


def test_build_discovery_report_deduplicates_queries_and_excludes_existing(
    tmp_path: Path,
) -> None:
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "2401.00002.json").write_text("{}", encoding="utf-8")

    report = build_discovery_report(
        topic=_topic(),
        raw_papers=[
            _paper("2401.00001", "First Paper", "direct"),
            _paper("2401.00001", "First Paper", "benchmark"),
            _paper("2401.00002", "Existing Paper", "direct"),
        ],
        topic_dir=tmp_path,
        include_existing=False,
        generated_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
    )

    assert report.query_count == 2
    assert report.candidate_count == 1
    assert report.excluded_existing == ["2401.00002"]
    assert report.candidates[0].paper_id == "2401.00001"
    assert report.candidates[0].matched_queries == ["direct", "benchmark"]
    assert report.candidates[0].query_rationales == ["direct purpose", "benchmark purpose"]


def test_build_discovery_report_include_existing_keeps_existing(tmp_path: Path) -> None:
    papers_dir = tmp_path / "papers"
    papers_dir.mkdir()
    (papers_dir / "2401.00002.json").write_text("{}", encoding="utf-8")

    report = build_discovery_report(
        topic=_topic(),
        raw_papers=[_paper("2401.00002", "Existing Paper", "direct")],
        topic_dir=tmp_path,
        include_existing=True,
        generated_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
    )

    assert report.candidate_count == 1
    assert report.excluded_existing == []


def test_discovery_renderers_and_artifact_writes(tmp_path: Path) -> None:
    report = build_discovery_report(
        topic=_topic(),
        raw_papers=[_paper("2401.00001", "First Paper", "direct")],
        topic_dir=tmp_path,
        include_existing=False,
        generated_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
    )

    markdown = render_discovery_markdown(report, _topic())
    manifest = render_discovery_manifest_draft(report)
    paths = write_discovery_artifacts(tmp_path, report, _topic())

    assert "# Discovery Candidates: Utility Navigation" in markdown
    assert "| direct |" in markdown
    assert "First Paper" in markdown
    manifest_raw = yaml.safe_load(manifest)
    assert manifest_raw["papers"][0]["paper_id"] == "2401.00001"
    assert manifest_raw["papers"][0]["pdf_url"] == "https://arxiv.org/pdf/2401.00001"
    assert manifest_raw["papers"][0]["source_url"] == "https://arxiv.org/abs/2401.00001"
    assert manifest_raw["papers"][0]["venue"] == "arXiv"
    assert manifest_raw["papers"][0]["year"] == 2024
    assert json.loads(paths["json"].read_text(encoding="utf-8"))["candidate_count"] == 1
    assert "First Paper" in paths["markdown"].read_text(encoding="utf-8")
    assert "pdf_url" in paths["manifest"].read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python -m pytest tests/survey/test_topic_discover.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'src.survey.topic_discover'`.

- [ ] **Step 3: Implement minimal service layer**

Create `src/survey/topic_discover.py` with:

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from src.reader.reading_renderer import validate_safe_paper_id
from src.survey.models import TopicProfile


@dataclass(frozen=True)
class RawDiscoveryPaper:
    arxiv_id: str
    title: str
    abstract: str
    authors: list[str]
    published: datetime
    categories: list[str]
    pdf_url: str
    source_url: str
    query_name: str
    query_purpose: str


@dataclass
class DiscoveryCandidate:
    paper_id: str
    arxiv_id: str
    title: str
    abstract: str
    authors: list[str]
    published: str
    year: int
    categories: list[str]
    pdf_url: str
    source_url: str
    matched_queries: list[str] = field(default_factory=list)
    query_rationales: list[str] = field(default_factory=list)
    status: str = "candidate"

    def to_dict(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "arxiv_id": self.arxiv_id,
            "title": self.title,
            "abstract": self.abstract,
            "authors": list(self.authors),
            "published": self.published,
            "year": self.year,
            "categories": list(self.categories),
            "pdf_url": self.pdf_url,
            "source_url": self.source_url,
            "matched_queries": list(self.matched_queries),
            "query_rationales": list(self.query_rationales),
            "status": self.status,
        }


@dataclass
class DiscoveryReport:
    topic_id: str
    topic_name: str
    source: str
    generated_at: str
    query_count: int
    candidate_count: int
    excluded_existing: list[str]
    candidates: list[DiscoveryCandidate]

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "topic_name": self.topic_name,
            "source": self.source,
            "generated_at": self.generated_at,
            "query_count": self.query_count,
            "candidate_count": self.candidate_count,
            "excluded_existing": list(self.excluded_existing),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def build_discovery_report(
    topic: TopicProfile,
    raw_papers: list[RawDiscoveryPaper],
    topic_dir: Path,
    include_existing: bool,
    generated_at: datetime,
) -> DiscoveryReport:
    existing_ids = _existing_reading_ids(topic_dir)
    by_id: dict[str, DiscoveryCandidate] = {}
    excluded_existing: set[str] = set()

    for raw in raw_papers:
        validate_safe_paper_id(raw.arxiv_id)
        if raw.arxiv_id in existing_ids and not include_existing:
            excluded_existing.add(raw.arxiv_id)
            continue
        candidate = by_id.get(raw.arxiv_id)
        if candidate is None:
            candidate = DiscoveryCandidate(
                paper_id=raw.arxiv_id,
                arxiv_id=raw.arxiv_id,
                title=raw.title,
                abstract=raw.abstract,
                authors=list(raw.authors),
                published=raw.published.date().isoformat(),
                year=raw.published.year,
                categories=list(raw.categories),
                pdf_url=raw.pdf_url,
                source_url=raw.source_url,
            )
            by_id[raw.arxiv_id] = candidate
        if raw.query_name not in candidate.matched_queries:
            candidate.matched_queries.append(raw.query_name)
        if raw.query_purpose not in candidate.query_rationales:
            candidate.query_rationales.append(raw.query_purpose)

    candidates = sorted(
        by_id.values(),
        key=lambda candidate: candidate.published,
        reverse=True,
    )
    return DiscoveryReport(
        topic_id=topic.topic_id,
        topic_name=topic.name,
        source="arxiv",
        generated_at=generated_at.isoformat(),
        query_count=len(topic.search_queries),
        candidate_count=len(candidates),
        excluded_existing=sorted(excluded_existing),
        candidates=candidates,
    )


def render_discovery_markdown(report: DiscoveryReport, topic: TopicProfile) -> str:
    lines = [
        f"# Discovery Candidates: {report.topic_name}",
        "",
        f"- Generated: {report.generated_at}",
        f"- Source: {report.source}",
        f"- Candidates: {report.candidate_count}",
        "",
        "## Queries",
        "",
        "| Name | Query | Purpose |",
        "| --- | --- | --- |",
    ]
    for query in topic.search_queries:
        lines.append(
            f"| {_cell(query.name)} | {_cell(query.query)} | {_cell(query.purpose)} |"
        )
    lines.extend(["", "## Candidates", ""])
    if not report.candidates:
        lines.append("No candidates.")
    else:
        lines.extend(
            [
                "| Paper | Year | Categories | Matched Queries | Source | Abstract Preview |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for candidate in report.candidates:
            preview = candidate.abstract[:240].replace("\n", " ").strip()
            lines.append(
                "| "
                + " | ".join(
                    [
                        _cell(candidate.title),
                        str(candidate.year),
                        _cell(", ".join(candidate.categories)),
                        _cell(", ".join(candidate.matched_queries)),
                        _cell(candidate.source_url),
                        _cell(preview),
                    ]
                )
                + " |"
            )
    return "\n".join(lines).rstrip() + "\n"


def render_discovery_manifest_draft(report: DiscoveryReport) -> str:
    raw = {
        "papers": [
            {
                "paper_id": candidate.paper_id,
                "title": candidate.title,
                "pdf_url": candidate.pdf_url,
                "source_url": candidate.source_url,
                "venue": "arXiv",
                "year": candidate.year,
            }
            for candidate in report.candidates
        ]
    }
    return yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)


def write_discovery_artifacts(
    topic_dir: Path,
    report: DiscoveryReport,
    topic: TopicProfile,
) -> dict[str, Path]:
    state_dir = topic_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    json_path = state_dir / "discovery_candidates.json"
    markdown_path = topic_dir / "discovery.md"
    manifest_path = topic_dir / "ingest_manifest.draft.yaml"
    json_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_discovery_markdown(report, topic), encoding="utf-8")
    manifest_path.write_text(render_discovery_manifest_draft(report), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path, "manifest": manifest_path}


def _existing_reading_ids(topic_dir: Path) -> set[str]:
    papers_dir = topic_dir / "papers"
    if not papers_dir.exists():
        return set()
    return {path.stem for path in papers_dir.glob("*.json")}


def _cell(value: str) -> str:
    return str(value).replace("|", r"\|").replace("\n", " ")
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
python -m pytest tests/survey/test_topic_discover.py -q
```

Expected: all tests in the new file pass.

- [ ] **Step 5: Commit**

```bash
git add src/survey/topic_discover.py tests/survey/test_topic_discover.py
git commit -m "feat: add topic discovery artifacts"
```

---

### Task 2: ArXiv Provider

**Files:**
- Create: `src/survey/arxiv_provider.py`
- Modify: `tests/survey/test_topic_discover.py`

- [ ] **Step 1: Write failing provider conversion tests**

Append to `tests/survey/test_topic_discover.py`:

```python
from types import SimpleNamespace

from src.survey.arxiv_provider import convert_arxiv_result


def test_convert_arxiv_result_to_raw_discovery_paper() -> None:
    result = SimpleNamespace(
        entry_id="https://arxiv.org/abs/2401.00001v2",
        title="  Example ArXiv Paper  ",
        summary="  Abstract text.  ",
        authors=[SimpleNamespace(name="A. Researcher")],
        published=datetime(2024, 1, 2, tzinfo=timezone.utc),
        categories=["cs.RO"],
        pdf_url="https://arxiv.org/pdf/2401.00001v2",
    )

    paper = convert_arxiv_result(
        result,
        query_name="direct",
        query_purpose="Direct query.",
    )

    assert paper.arxiv_id == "2401.00001"
    assert paper.title == "Example ArXiv Paper"
    assert paper.abstract == "Abstract text."
    assert paper.authors == ["A. Researcher"]
    assert paper.source_url == "https://arxiv.org/abs/2401.00001"
    assert paper.pdf_url == "https://arxiv.org/pdf/2401.00001"
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
python -m pytest tests/survey/test_topic_discover.py::test_convert_arxiv_result_to_raw_discovery_paper -q
```

Expected: fail with `ModuleNotFoundError: No module named 'src.survey.arxiv_provider'`.

- [ ] **Step 3: Implement provider conversion and async provider**

Create `src/survey/arxiv_provider.py`:

```python
from __future__ import annotations

import asyncio
import re

import arxiv

from src.survey.topic_discover import RawDiscoveryPaper

_VERSION_SUFFIX = re.compile(r"v\d+$")


class ArxivDiscoveryProvider:
    def __init__(self, delay_seconds: float = 3.0) -> None:
        self.client = arxiv.Client(
            page_size=100,
            delay_seconds=delay_seconds,
            num_retries=3,
        )

    async def search(
        self,
        query: str,
        query_name: str,
        query_purpose: str,
        max_results: int,
        sort: str,
    ) -> list[RawDiscoveryPaper]:
        sort_by = (
            arxiv.SortCriterion.Relevance
            if sort == "relevance"
            else arxiv.SortCriterion.SubmittedDate
        )
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=sort_by,
            sort_order=arxiv.SortOrder.Descending,
        )
        results = await asyncio.to_thread(lambda: list(self.client.results(search)))
        return [
            convert_arxiv_result(
                result,
                query_name=query_name,
                query_purpose=query_purpose,
            )
            for result in results
        ]


def convert_arxiv_result(
    result,
    query_name: str,
    query_purpose: str,
) -> RawDiscoveryPaper:
    arxiv_id = _normalize_arxiv_id(result.entry_id.split("/abs/")[-1])
    return RawDiscoveryPaper(
        arxiv_id=arxiv_id,
        title=result.title.strip(),
        abstract=result.summary.strip(),
        authors=[author.name for author in result.authors],
        published=result.published,
        categories=list(result.categories),
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
        source_url=f"https://arxiv.org/abs/{arxiv_id}",
        query_name=query_name,
        query_purpose=query_purpose,
    )


def _normalize_arxiv_id(raw: str) -> str:
    return _VERSION_SUFFIX.sub("", raw.strip())
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
python -m pytest tests/survey/test_topic_discover.py -q
```

Expected: all topic discovery tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/survey/arxiv_provider.py tests/survey/test_topic_discover.py
git commit -m "feat: add arxiv discovery provider"
```

---

### Task 3: Discover CLI And Dispatch

**Files:**
- Create: `src/survey/discover_cli.py`
- Modify: `src/survey/topic_cli.py`
- Modify: `run.py`
- Modify: `tests/survey/test_topic_discover.py`

- [ ] **Step 1: Write failing CLI tests**

Append to `tests/survey/test_topic_discover.py`:

```python
import asyncio
from types import SimpleNamespace

import pytest

from run import build_parser


def _write_topic(topic_dir: Path, search_queries: bool = True) -> Path:
    topic_dir.mkdir(parents=True, exist_ok=True)
    query_block = """
    search_queries:
      - name: direct
        query: '"utility" "navigation"'
        purpose: Direct query.
    """ if search_queries else "search_queries: []\n"
    topic_path = topic_dir / "topic.yaml"
    topic_path.write_text(
        textwrap.dedent(
            f"""
            topic_id: utility_nav
            name: Utility Navigation
            description: Task-conditioned utility over 3D memory.
            intent: Find candidate papers.
            {query_block}
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return topic_path


class FakeProvider:
    def __init__(self) -> None:
        self.calls = []

    async def search(self, query, query_name, query_purpose, max_results, sort):
        self.calls.append(
            {
                "query": query,
                "query_name": query_name,
                "query_purpose": query_purpose,
                "max_results": max_results,
                "sort": sort,
            }
        )
        return [_paper("2401.00001", "First Paper", query_name)]


def test_topic_discover_parser_accepts_options() -> None:
    args = build_parser().parse_args(
        [
            "topic",
            "discover",
            "--topic",
            "topic.yaml",
            "--max-results-per-query",
            "5",
            "--sort",
            "relevance",
            "--days-lookback",
            "30",
            "--include-existing",
        ]
    )

    assert args.command == "topic"
    assert args.topic_command == "discover"
    assert args.topic == "topic.yaml"
    assert args.max_results_per_query == 5
    assert args.sort == "relevance"
    assert args.days_lookback == 30
    assert args.include_existing is True


@pytest.mark.parametrize(
    "argv",
    [
        ["topic", "discover", "--topic", "topic.yaml", "--sort", "bad"],
        ["topic", "discover", "--topic", "topic.yaml", "--max-results-per-query", "0"],
        ["topic", "discover", "--topic", "topic.yaml", "--days-lookback", "0"],
    ],
)
def test_topic_discover_parser_rejects_invalid_options(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(argv)


def test_cmd_topic_discover_writes_artifacts_with_fake_provider(tmp_path: Path) -> None:
    from src.survey.discover_cli import cmd_topic_discover

    topic_path = _write_topic(tmp_path / "utility_nav")
    provider = FakeProvider()

    report = asyncio.run(
        cmd_topic_discover(
            SimpleNamespace(
                topic=str(topic_path),
                max_results_per_query=5,
                sort="submitted",
                days_lookback=365,
                include_existing=False,
            ),
            provider=provider,
        )
    )

    assert report.candidate_count == 1
    assert provider.calls[0]["max_results"] == 5
    assert (topic_path.parent / "state" / "discovery_candidates.json").exists()
    assert (topic_path.parent / "discovery.md").exists()
    assert (topic_path.parent / "ingest_manifest.draft.yaml").exists()


def test_cmd_topic_discover_empty_queries_fails_before_provider(tmp_path: Path) -> None:
    from src.survey.discover_cli import cmd_topic_discover

    topic_path = _write_topic(tmp_path / "utility_nav", search_queries=False)
    provider = FakeProvider()

    with pytest.raises(SystemExit, match="search_queries"):
        asyncio.run(
            cmd_topic_discover(
                SimpleNamespace(
                    topic=str(topic_path),
                    max_results_per_query=5,
                    sort="submitted",
                    days_lookback=365,
                    include_existing=False,
                ),
                provider=provider,
            )
        )

    assert provider.calls == []
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
python -m pytest tests/survey/test_topic_discover.py::test_topic_discover_parser_accepts_options tests/survey/test_topic_discover.py::test_cmd_topic_discover_writes_artifacts_with_fake_provider -q
```

Expected: fail because parser/CLI module does not exist.

- [ ] **Step 3: Implement discover CLI**

Create `src/survey/discover_cli.py`:

```python
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.survey.arxiv_provider import ArxivDiscoveryProvider
from src.survey.cli import _load_topic, _validate_topic_path
from src.survey.topic_discover import (
    RawDiscoveryPaper,
    build_discovery_report,
    write_discovery_artifacts,
)


async def cmd_topic_discover(args, provider=None):
    topic_path = Path(args.topic)
    topic = _load_topic(topic_path)
    topic_dir = topic_path.parent
    _validate_topic_path(topic, topic_dir)
    if not topic.search_queries:
        raise SystemExit("topic discover requires topic.search_queries; run survey refine first.")

    provider = provider if provider is not None else ArxivDiscoveryProvider()
    raw_papers: list[RawDiscoveryPaper] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days_lookback)
    for query in topic.search_queries:
        results = await provider.search(
            query=query.query,
            query_name=query.name,
            query_purpose=query.purpose,
            max_results=args.max_results_per_query,
            sort=args.sort,
        )
        raw_papers.extend([paper for paper in results if paper.published >= cutoff])

    report = build_discovery_report(
        topic=topic,
        raw_papers=raw_papers,
        topic_dir=topic_dir,
        include_existing=args.include_existing,
        generated_at=datetime.now(timezone.utc),
    )
    paths = write_discovery_artifacts(topic_dir, report, topic)
    print(f"Candidates JSON: {paths['json']}")
    print(f"Discovery Markdown: {paths['markdown']}")
    print(f"Draft manifest: {paths['manifest']}")
    print(f"Candidates: {report.candidate_count}")
    print(f"Excluded existing: {len(report.excluded_existing)}")
    return report


def run_topic_discover(args) -> None:
    asyncio.run(cmd_topic_discover(args))
```

- [ ] **Step 4: Wire dispatch**

Modify `src/survey/topic_cli.py`:

```python
def run_topic_command(args) -> None:
    if args.topic_command == "discover":
        from src.survey.discover_cli import run_topic_discover

        run_topic_discover(args)
        return
    if args.topic_command == "ingest":
        from src.survey.ingest_cli import run_topic_ingest

        run_topic_ingest(args)
        return
    if args.topic_command == "update":
        asyncio.run(cmd_topic_update(args))
        return
    raise SystemExit(f"Unknown topic command: {args.topic_command}")
```

Modify `run.py` parser after existing topic subcommands:

```python
    topic_discover_parser = topic_subparsers.add_parser(
        "discover",
        help="Discover arXiv candidate papers for one topic",
    )
    topic_discover_parser.add_argument("--topic", required=True, help="Path to topic.yaml")
    topic_discover_parser.add_argument(
        "--max-results-per-query",
        type=int,
        default=20,
        help="Maximum arXiv results per topic query",
    )
    topic_discover_parser.add_argument(
        "--sort",
        choices=["submitted", "relevance"],
        default="submitted",
        help="ArXiv sort mode",
    )
    topic_discover_parser.add_argument(
        "--days-lookback",
        type=int,
        default=365,
        help="Only keep papers published within this many days",
    )
    topic_discover_parser.add_argument(
        "--include-existing",
        action="store_true",
        help="Include papers that already have topic reading packages",
    )
```

Also extend `PaperReaderArgumentParser.parse_args`:

```python
        if (
            getattr(parsed, "command", None) == "topic"
            and getattr(parsed, "topic_command", None) == "discover"
        ):
            if getattr(parsed, "max_results_per_query", 1) < 1:
                self.error("topic discover requires --max-results-per-query >= 1")
            if getattr(parsed, "days_lookback", 1) < 1:
                self.error("topic discover requires --days-lookback >= 1")
```

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```bash
python -m pytest tests/survey/test_topic_discover.py -q
```

Expected: all topic discovery tests pass.

- [ ] **Step 6: Commit**

```bash
git add run.py src/survey/discover_cli.py src/survey/topic_cli.py tests/survey/test_topic_discover.py
git commit -m "feat: add topic discover CLI"
```

---

### Task 4: Full Verification And Smoke

**Files:**
- Modify if needed: implementation and tests
- Local ignored artifacts under `data/topics-smoke/...`

- [ ] **Step 1: Run full test suite**

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

- [ ] **Step 3: Run import check**

Run:

```bash
python -c "import src.survey.topic_discover; import src.survey.discover_cli; import src.survey.arxiv_provider"
```

Expected: exits 0.

- [ ] **Step 4: Run arXiv smoke**

Run:

```bash
python run.py topic discover --topic data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/topic.yaml --max-results-per-query 3 --days-lookback 3650
```

Expected: command exits 0 and prints paths for the three discovery artifacts.

If the network request fails or times out, retry once with the configured proxy, then report the failure with the error text.

- [ ] **Step 5: Inspect smoke report**

Run:

```bash
python -c "import json; p='data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/state/discovery_candidates.json'; d=json.load(open(p, encoding='utf-8')); print(d['query_count'], d['candidate_count'], d['source'])"
```

Expected: prints query count, candidate count, and `arxiv`.

- [ ] **Step 6: Final review**

Request a final code review over the MVP-7 commit range. Fix Critical and Important findings before completion.

- [ ] **Step 7: Push branch and comment on PR**

Run:

```bash
git push
```

Then add a PR comment with:

- feature summary;
- verification commands and results;
- smoke result;
- note that MVP-7 does not download or ingest papers.
