from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Optional

from src.reader.staged_models import PageText


def extract_pages_from_text_file(path: Path) -> list[PageText]:
    text = normalize_extracted_text(path.read_text(encoding="utf-8"))
    return [PageText(page=1, text=text, char_start=0, char_end=len(text))]


def extract_pages_from_pdf(path: Path, max_pages: Optional[int] = None) -> list[PageText]:
    """
    Extract page text from a PDF.

    PageText.text preserves each page.get_text() result exactly. PageText.char_start
    and PageText.char_end are offsets into a virtual full text formed by joining
    page texts with a single "\n" separator between pages.
    """
    limit = None if max_pages is None else max(0, max_pages)
    if limit == 0:
        return []

    pages = _extract_pages_with_pymupdf4llm(path, limit)
    if pages is not None:
        return pages

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
            if limit is not None and index >= limit:
                break

            text = normalize_extracted_text(page.get_text())
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


def normalize_extracted_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def _extract_pages_with_pymupdf4llm(
    path: Path,
    limit: Optional[int],
) -> Optional[list[PageText]]:
    try:
        import pymupdf4llm
    except ImportError:
        return None

    kwargs: dict[str, object] = {"page_chunks": True}
    if limit is not None:
        kwargs["pages"] = list(range(limit))
    try:
        chunks = pymupdf4llm.to_markdown(str(path), **kwargs)
    except Exception:
        return None
    if not isinstance(chunks, list):
        return None

    pages: list[PageText] = []
    char_start = 0
    for index, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            return None
        metadata = chunk.get("metadata", {})
        page_number = _extract_chunk_page_number(metadata, default=index + 1)
        text = normalize_extracted_text(str(chunk.get("text", "")))
        char_end = char_start + len(text)
        pages.append(
            PageText(
                page=page_number,
                text=text,
                char_start=char_start,
                char_end=char_end,
            )
        )
        char_start = char_end + 1
    return pages


def _extract_chunk_page_number(metadata: object, default: int) -> int:
    if not isinstance(metadata, dict):
        return default
    for key in ("page", "page_number", "page_num"):
        value = metadata.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return default
