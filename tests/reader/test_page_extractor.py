from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from src.reader.page_extractor import extract_pages_from_pdf, extract_pages_from_text_file


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


def test_extract_pages_from_pdf_uses_lazy_fitz(
    monkeypatch, tmp_path: Path
) -> None:
    class FakePage:
        def __init__(self, text: str) -> None:
            self.text = text

        def get_text(self) -> str:
            return self.text

    class FakeDoc:
        def __init__(self) -> None:
            self.closed = False
            self.pages = [FakePage("First page"), FakePage("Second page")]

        def __iter__(self):
            return iter(self.pages)

        def close(self) -> None:
            self.closed = True

    fake_doc = FakeDoc()

    def fake_open(path: Path) -> FakeDoc:
        return fake_doc

    fake_fitz = SimpleNamespace(open=fake_open)
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)
    pdf_path = tmp_path / "paper.pdf"

    pages = extract_pages_from_pdf(pdf_path, max_pages=5)

    assert [page.page for page in pages] == [1, 2]
    assert pages[0].text == "First page\n"
    assert pages[1].char_start == len("First page\n")
    assert fake_doc.closed is True
