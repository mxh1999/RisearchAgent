from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.reader.page_extractor import (
    extract_pages_from_pdf,
    extract_pages_from_text_file,
    normalize_extracted_text,
)


class FakePage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.get_text_calls = 0

    def get_text(self) -> str:
        self.get_text_calls += 1
        return self.text


class FakeDoc:
    def __init__(self, texts: list[str]) -> None:
        self.closed = False
        self.iterations = 0
        self.pages = [FakePage(text) for text in texts]

    def __iter__(self):
        self.iterations += 1
        return iter(self.pages)

    def close(self) -> None:
        self.closed = True


def install_fake_fitz(monkeypatch, fake_doc: FakeDoc) -> None:
    def fake_open(path: Path) -> FakeDoc:
        return fake_doc

    fake_fitz = SimpleNamespace(open=fake_open)
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)


def install_fake_pymupdf4llm(monkeypatch, chunks) -> list[dict]:
    calls = []

    def fake_to_markdown(path, **kwargs):
        calls.append({"path": path, **kwargs})
        return chunks

    fake_module = SimpleNamespace(to_markdown=fake_to_markdown)
    monkeypatch.setitem(sys.modules, "pymupdf4llm", fake_module)
    return calls


def test_extract_pages_from_text_file(tmp_path: Path) -> None:
    text = "First line\nSecond line\n"
    path = tmp_path / "paper.txt"
    path.write_text(text, encoding="utf-8")

    pages = extract_pages_from_text_file(path)

    assert len(pages) == 1
    assert pages[0].page == 1
    assert pages[0].char_start == 0
    assert pages[0].char_end == len(text)
    assert "Second line" in pages[0].text


def test_normalize_extracted_text_expands_pdf_ligatures() -> None:
    assert normalize_extracted_text("e\ufb00icient \ufb01eld \ufb02ow") == (
        "efficient field flow"
    )


def test_import_page_extractor_does_not_require_fitz(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "src.reader.page_extractor", raising=False)
    monkeypatch.setitem(sys.modules, "fitz", None)

    module = importlib.import_module("src.reader.page_extractor")

    assert hasattr(module, "extract_pages_from_pdf")


def test_extract_pages_from_pdf_uses_lazy_fitz(monkeypatch, tmp_path: Path) -> None:
    fake_doc = FakeDoc(["First page", "Second page"])
    install_fake_fitz(monkeypatch, fake_doc)
    pdf_path = tmp_path / "paper.pdf"

    pages = extract_pages_from_pdf(pdf_path, max_pages=5)

    assert [page.page for page in pages] == [1, 2]
    assert pages[0].text == "First page"
    assert pages[0].char_end == len("First page")
    assert pages[1].char_start == len("First page\n")
    assert fake_doc.closed is True


def test_extract_pages_from_pdf_prefers_pymupdf4llm_page_chunks(
    monkeypatch, tmp_path: Path
) -> None:
    chunks = [
        {"metadata": {"page": 1}, "text": "Intro with e\ufb00icient layout."},
        {"metadata": {"page": 2}, "text": "| Method | SPL |\n|---|---:|"},
    ]
    calls = install_fake_pymupdf4llm(monkeypatch, chunks)
    fake_doc = FakeDoc(["Fallback should not be read"])
    install_fake_fitz(monkeypatch, fake_doc)

    pages = extract_pages_from_pdf(tmp_path / "paper.pdf", max_pages=2)

    assert [page.page for page in pages] == [1, 2]
    assert pages[0].text == "Intro with efficient layout."
    assert pages[1].text.startswith("| Method | SPL |")
    assert pages[1].char_start == len(pages[0].text) + 1
    assert calls == [
        {
            "path": str(tmp_path / "paper.pdf"),
            "page_chunks": True,
            "pages": [0, 1],
        }
    ]
    assert fake_doc.pages[0].get_text_calls == 0


@pytest.mark.parametrize("max_pages", [None, 3])
def test_extract_pages_from_pdf_reads_all_pages_when_unlimited(
    monkeypatch, tmp_path: Path, max_pages
) -> None:
    fake_doc = FakeDoc(["First page", "Second page", "Third page"])
    install_fake_fitz(monkeypatch, fake_doc)

    pages = extract_pages_from_pdf(tmp_path / "paper.pdf", max_pages=max_pages)

    assert [page.text for page in pages] == ["First page", "Second page", "Third page"]
    assert [page.get_text_calls for page in fake_doc.pages] == [1, 1, 1]
    assert fake_doc.closed is True


def test_extract_pages_from_pdf_reads_at_most_max_pages(
    monkeypatch, tmp_path: Path
) -> None:
    fake_doc = FakeDoc(["First page", "Second page"])
    install_fake_fitz(monkeypatch, fake_doc)

    pages = extract_pages_from_pdf(tmp_path / "paper.pdf", max_pages=1)

    assert [page.text for page in pages] == ["First page"]
    assert [page.get_text_calls for page in fake_doc.pages] == [1, 0]
    assert fake_doc.closed is True


@pytest.mark.parametrize("max_pages", [0, -1])
def test_extract_pages_from_pdf_non_positive_max_pages_reads_no_page_text(
    monkeypatch, tmp_path: Path, max_pages: int
) -> None:
    fake_doc = FakeDoc(["First page", "Second page"])
    install_fake_fitz(monkeypatch, fake_doc)

    pages = extract_pages_from_pdf(tmp_path / "paper.pdf", max_pages=max_pages)

    assert pages == []
    assert fake_doc.iterations == 0
    assert [page.get_text_calls for page in fake_doc.pages] == [0, 0]
    assert fake_doc.closed is False
