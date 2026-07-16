from __future__ import annotations

import asyncio
import json
import textwrap
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from run import build_parser
from src.survey.topic_ingest import load_ingest_manifest


def _write_topic(topic_dir: Path, topic_id: str = "utility_nav") -> Path:
    topic_dir.mkdir(parents=True, exist_ok=True)
    topic_path = topic_dir / "topic.yaml"
    topic_path.write_text(
        textwrap.dedent(
            f"""
            topic_id: {topic_id}
            name: Utility Navigation
            description: Task-conditioned utility over 3D memory.
            intent: Build a focused reading set.
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return topic_path


def _write_discovery(topic_dir: Path, candidates: list[dict[str, object]]) -> Path:
    state_dir = topic_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "discovery_candidates.json"
    path.write_text(
        json.dumps(
            {
                "topic_id": "utility_nav",
                "topic_name": "Utility Navigation",
                "source": "arxiv",
                "generated_at": "2026-05-21T00:00:00+00:00",
                "query_count": 1,
                "candidate_count": len(candidates),
                "excluded_existing": [],
                "candidates": candidates,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _candidate(
    paper_id: str,
    *,
    title: str | None = None,
    status: str = "candidate",
    year: int = 2024,
) -> dict[str, object]:
    return {
        "paper_id": paper_id,
        "arxiv_id": paper_id,
        "title": title or f"Paper {paper_id}",
        "abstract": "abstract",
        "authors": ["A. Researcher"],
        "published": f"{year}-01-01",
        "year": year,
        "categories": ["cs.RO"],
        "pdf_url": f"https://arxiv.org/pdf/{paper_id}",
        "source_url": f"https://arxiv.org/abs/{paper_id}",
        "matched_queries": ["direct"],
        "query_rationales": ["Direct query"],
        "status": status,
    }


class FakeDownloader:
    def __init__(self, fail_on: set[str] | None = None) -> None:
        self.calls: list[tuple[str, Path]] = []
        self.fail_on = fail_on or set()

    async def __call__(self, pdf_url: str, target_path: Path) -> None:
        self.calls.append((pdf_url, target_path))
        paper_id = target_path.stem
        if paper_id in self.fail_on:
            raise RuntimeError(f"download failed: {paper_id}")
        target_path.write_bytes(f"%PDF-1.4\n{paper_id}\n".encode("utf-8"))


class FakeSourceDownloader:
    def __init__(self, fail_on: set[str] | None = None) -> None:
        self.calls: list[tuple[str, Path]] = []
        self.fail_on = fail_on or set()

    async def __call__(self, source_url: str, target_path: Path) -> None:
        self.calls.append((source_url, target_path))
        paper_id = target_path.stem
        if paper_id in self.fail_on:
            raise RuntimeError(f"source download failed: {paper_id}")
        target_path.write_bytes(f"source for {paper_id}\n".encode("utf-8"))


def test_materialize_topic_downloads_writes_pdfs_manifest_and_report(
    tmp_path: Path,
) -> None:
    from src.survey.topic_download import materialize_topic_downloads

    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    discovery_path = _write_discovery(
        topic_dir,
        [
            _candidate("2605.00001", title="First Candidate", year=2026),
            _candidate("2605.00002", title="Rejected Candidate", status="reject"),
            _candidate("2605.00003", title="Second Candidate", year=2026),
        ],
    )
    downloader = FakeDownloader()

    report = asyncio.run(
        materialize_topic_downloads(
            topic_path=topic_path,
            candidates_path=discovery_path,
            manifest_path=topic_dir / "ingest_manifest.yaml",
            limit=10,
            include_existing=False,
            force=False,
            download_one=downloader,
        )
    )

    assert [row.paper_id for row in report.downloaded] == ["2605.00001", "2605.00003"]
    assert report.reused == []
    assert report.skipped == [{"paper_id": "2605.00002", "reason": "status: reject"}]
    assert report.failed == []
    assert [call[1] for call in downloader.calls] == [
        topic_dir / "pdfs" / "2605.00001.pdf",
        topic_dir / "pdfs" / "2605.00003.pdf",
    ]
    manifest = load_ingest_manifest(topic_dir / "ingest_manifest.yaml")
    assert [entry.paper_id for entry in manifest.papers] == ["2605.00001", "2605.00003"]
    assert manifest.papers[0].title == "First Candidate"
    assert manifest.papers[0].source_kind == "pdf"
    assert manifest.papers[0].source_path == (topic_dir / "pdfs" / "2605.00001.pdf").resolve()
    assert manifest.papers[0].metadata == {
        "source_url": "https://arxiv.org/abs/2605.00001",
        "venue": "arXiv",
        "year": 2026,
    }
    raw_report = json.loads(
        (topic_dir / "state" / "download_report.json").read_text(encoding="utf-8")
    )
    assert raw_report["downloaded"] == ["2605.00001", "2605.00003"]
    assert raw_report["manifest_path"] == str(topic_dir / "ingest_manifest.yaml")


def test_materialize_topic_downloads_downloads_arxiv_source_archives(
    tmp_path: Path,
) -> None:
    from src.survey.topic_download import materialize_topic_downloads

    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    discovery_path = _write_discovery(topic_dir, [_candidate("2605.00001")])
    pdf_downloader = FakeDownloader()
    source_downloader = FakeSourceDownloader()

    report = asyncio.run(
        materialize_topic_downloads(
            topic_path=topic_path,
            candidates_path=discovery_path,
            manifest_path=topic_dir / "ingest_manifest.yaml",
            limit=10,
            include_existing=False,
            force=False,
            download_one=pdf_downloader,
            download_source=source_downloader,
        )
    )

    assert report.source_downloaded == ["2605.00001"]
    assert report.source_failed == []
    assert source_downloader.calls == [
        (
            "https://arxiv.org/e-print/2605.00001",
            topic_dir / "sources" / "2605.00001.tar.gz",
        )
    ]
    raw_manifest = (topic_dir / "ingest_manifest.yaml").read_text(encoding="utf-8")
    assert "source_archive: sources/2605.00001.tar.gz" in raw_manifest
    manifest = load_ingest_manifest(topic_dir / "ingest_manifest.yaml")
    assert manifest.papers[0].source_archive_path == (
        topic_dir / "sources" / "2605.00001.tar.gz"
    ).resolve()


def test_materialize_topic_downloads_reuses_existing_pdf_and_respects_limit(
    tmp_path: Path,
) -> None:
    from src.survey.topic_download import materialize_topic_downloads

    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    _write_discovery(
        topic_dir,
        [
            _candidate("2605.00001"),
            _candidate("2605.00002"),
            _candidate("2605.00003"),
        ],
    )
    pdf_path = topic_dir / "pdfs" / "2605.00001.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4\nexisting\n")
    downloader = FakeDownloader()

    report = asyncio.run(
        materialize_topic_downloads(
            topic_path=topic_path,
            candidates_path=topic_dir / "state" / "discovery_candidates.json",
            manifest_path=topic_dir / "ingest_manifest.yaml",
            limit=2,
            include_existing=False,
            force=False,
            download_one=downloader,
        )
    )

    assert [row.paper_id for row in report.reused] == ["2605.00001"]
    assert [row.paper_id for row in report.downloaded] == ["2605.00002"]
    assert [item["paper_id"] for item in report.skipped] == ["2605.00003"]
    assert report.skipped[-1]["reason"] == "limit"
    assert [call[1].name for call in downloader.calls] == ["2605.00002.pdf"]


def test_materialize_topic_downloads_preserves_discovery_order_in_manifest(
    tmp_path: Path,
) -> None:
    from src.survey.topic_download import materialize_topic_downloads

    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    _write_discovery(
        topic_dir,
        [
            _candidate("2605.00001"),
            _candidate("2605.00002"),
        ],
    )
    reused_pdf = topic_dir / "pdfs" / "2605.00002.pdf"
    reused_pdf.parent.mkdir(parents=True)
    reused_pdf.write_bytes(b"%PDF-1.4\nexisting\n")

    asyncio.run(
        materialize_topic_downloads(
            topic_path=topic_path,
            candidates_path=topic_dir / "state" / "discovery_candidates.json",
            manifest_path=topic_dir / "ingest_manifest.yaml",
            limit=10,
            include_existing=False,
            force=False,
            download_one=FakeDownloader(),
        )
    )

    manifest = load_ingest_manifest(topic_dir / "ingest_manifest.yaml")
    assert [entry.paper_id for entry in manifest.papers] == ["2605.00001", "2605.00002"]


def test_materialize_topic_downloads_skips_existing_reading_package(
    tmp_path: Path,
) -> None:
    from src.survey.topic_download import materialize_topic_downloads

    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    _write_discovery(topic_dir, [_candidate("2605.00001"), _candidate("2605.00002")])
    papers_dir = topic_dir / "papers"
    papers_dir.mkdir()
    (papers_dir / "2605.00001.json").write_text("{}", encoding="utf-8")
    downloader = FakeDownloader()

    report = asyncio.run(
        materialize_topic_downloads(
            topic_path=topic_path,
            candidates_path=topic_dir / "state" / "discovery_candidates.json",
            manifest_path=topic_dir / "ingest_manifest.yaml",
            limit=10,
            include_existing=False,
            force=False,
            download_one=downloader,
        )
    )

    assert report.skipped == [
        {"paper_id": "2605.00001", "reason": "existing reading package"}
    ]
    assert [row.paper_id for row in report.downloaded] == ["2605.00002"]


def test_materialize_topic_downloads_records_failed_downloads_without_manifest_entry(
    tmp_path: Path,
) -> None:
    from src.survey.topic_download import materialize_topic_downloads

    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    _write_discovery(topic_dir, [_candidate("2605.00001"), _candidate("2605.00002")])
    downloader = FakeDownloader(fail_on={"2605.00001"})

    report = asyncio.run(
        materialize_topic_downloads(
            topic_path=topic_path,
            candidates_path=topic_dir / "state" / "discovery_candidates.json",
            manifest_path=topic_dir / "ingest_manifest.yaml",
            limit=10,
            include_existing=False,
            force=False,
            download_one=downloader,
        )
    )

    assert report.failed == [
        {"paper_id": "2605.00001", "error": "download failed: 2605.00001"}
    ]
    manifest = load_ingest_manifest(topic_dir / "ingest_manifest.yaml")
    assert [entry.paper_id for entry in manifest.papers] == ["2605.00002"]


def test_materialize_topic_downloads_rejects_topic_id_mismatch(tmp_path: Path) -> None:
    from src.survey.topic_download import materialize_topic_downloads

    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    discovery_path = _write_discovery(topic_dir, [_candidate("2605.00001")])
    raw = json.loads(discovery_path.read_text(encoding="utf-8"))
    raw["topic_id"] = "wrong_topic"
    discovery_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="topic_id"):
        asyncio.run(
            materialize_topic_downloads(
                topic_path=topic_path,
                candidates_path=discovery_path,
                manifest_path=topic_dir / "ingest_manifest.yaml",
                limit=10,
                include_existing=False,
                force=False,
                download_one=FakeDownloader(),
            )
        )


def test_default_download_pdf_downloads_from_http_server(tmp_path: Path) -> None:
    from src.survey.topic_download import default_download_pdf

    serve_dir = tmp_path / "serve"
    serve_dir.mkdir()
    (serve_dir / "paper.pdf").write_bytes(b"%PDF-1.4\nserved\n")

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(serve_dir), **kwargs)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        target_path = tmp_path / "downloads" / "paper.pdf"
        asyncio.run(
            default_download_pdf(
                f"http://127.0.0.1:{server.server_port}/paper.pdf",
                target_path,
            )
        )
    finally:
        server.shutdown()
        server.server_close()

    assert target_path.read_bytes() == b"%PDF-1.4\nserved\n"
    assert not (tmp_path / "downloads" / "paper.pdf.tmp").exists()


def test_topic_download_parser_accepts_options() -> None:
    args = build_parser().parse_args(
        [
            "topic",
            "download",
            "--topic",
            "data/topics/utility_nav/topic.yaml",
            "--candidates",
            "candidates.json",
            "--manifest",
            "ingest_manifest.yaml",
            "--limit",
            "3",
            "--include-existing",
            "--force",
        ]
    )

    assert args.command == "topic"
    assert args.topic_command == "download"
    assert args.topic == "data/topics/utility_nav/topic.yaml"
    assert args.candidates == "candidates.json"
    assert args.manifest == "ingest_manifest.yaml"
    assert args.limit == 3
    assert args.all is False
    assert args.include_existing is True
    assert args.force is True


def test_topic_download_parser_accepts_all() -> None:
    args = build_parser().parse_args(
        [
            "topic",
            "download",
            "--topic",
            "data/topics/utility_nav/topic.yaml",
            "--all",
        ]
    )

    assert args.limit == 10
    assert args.all is True


@pytest.mark.parametrize(
    "argv",
    [
        [
            "topic",
            "download",
            "--topic",
            "data/topics/utility_nav/topic.yaml",
            "--limit",
            "0",
        ],
        [
            "topic",
            "download",
            "--topic",
            "data/topics/utility_nav/topic.yaml",
            "--all",
            "--limit",
            "3",
        ],
        [
            "topic",
            "download",
            "--topic",
            "data/topics/utility_nav/topic.yaml",
            "--all",
            "--limit=3",
        ],
    ],
)
def test_topic_download_parser_rejects_invalid_limits(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(argv)


def test_cmd_topic_download_reports_local_errors_before_network(
    tmp_path: Path,
) -> None:
    from src.survey import download_cli

    topic_dir = tmp_path / "utility_nav"
    topic_path = _write_topic(topic_dir)
    args = SimpleNamespace(
        topic=str(topic_path),
        candidates=None,
        manifest=None,
        limit=10,
        all=False,
        include_existing=False,
        force=False,
    )

    with pytest.raises(SystemExit, match="discovery candidates"):
        asyncio.run(
            download_cli.cmd_topic_download(
                args,
                download_one=lambda _url, _target: pytest.fail(
                    "download should not be called"
                ),
            )
        )
