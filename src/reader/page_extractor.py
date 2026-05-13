from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.reader.staged_models import PageText


def extract_pages_from_text_file(path: Path) -> list[PageText]:
    text = path.read_text(encoding="utf-8")
    return [PageText(page=1, text=text, char_start=0, char_end=len(text))]


def extract_pages_from_pdf(path: Path, max_pages: Optional[int] = None) -> list[PageText]:
    """
    Extract page text from a PDF.

    PageText.text preserves each page.get_text() result exactly. PageText.char_start
    and PageText.char_end are offsets into a virtual full text formed by joining
    page texts with a single "\n" separator between pages.
    """
    limit = None if max_pages is None else max(0, max_pages)

    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is required for PDF extraction. Install project requirements."
        ) from exc

    doc = fitz.open(path)
    pages: list[PageText] = []
    char_start = 0

    try:
        if limit == 0:
            return pages

        for index, page in enumerate(doc):
            if limit is not None and index >= limit:
                break

            text = page.get_text()
            char_end = char_start + len(text)
            pages.append(
                PageText(
                    page=index + 1,
                    text=text,
                    char_start=char_start,
                    char_end=char_end,
                )
            )
            char_start = char_end + 1
    finally:
        doc.close()

    return pages
