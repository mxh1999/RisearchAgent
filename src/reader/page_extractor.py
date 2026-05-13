from __future__ import annotations

from pathlib import Path
from typing import Optional

from src.reader.staged_models import PageText


def extract_pages_from_text_file(path: Path) -> list[PageText]:
    text = path.read_text(encoding="utf-8")
    return [PageText(page=1, text=text, char_start=0, char_end=len(text))]


def extract_pages_from_pdf(path: Path, max_pages: Optional[int] = None) -> list[PageText]:
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
        for index, page in enumerate(doc):
            if max_pages is not None and index >= max_pages:
                break

            text = page.get_text()
            if not text.endswith("\n"):
                text += "\n"

            char_end = char_start + len(text)
            pages.append(
                PageText(
                    page=index + 1,
                    text=text,
                    char_start=char_start,
                    char_end=char_end,
                )
            )
            char_start = char_end
    finally:
        doc.close()

    return pages
