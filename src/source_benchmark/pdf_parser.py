from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from src.reader.page_extractor import extract_pages_from_pdf, normalize_extracted_text
from src.reader.staged_models import PageText

PARSER_NAME = "pymupdf4llm-section-heuristic"
PARSER_VERSION = "0.1.0"
SOURCE_TYPE = "pdf"
DEFAULT_CHUNK_TARGET_TOKENS = 900
DEFAULT_CHUNK_MAX_TOKENS = 1200

NORMALIZED_SECTION_TYPES = {
    "abstract",
    "introduction",
    "related_work",
    "background",
    "method",
    "experiments",
    "results",
    "discussion",
    "limitations",
    "conclusion",
    "appendix",
    "references",
    "other",
}

DownloadPdf = Callable[[str, Path], None]


def parse_pdf_paper(
    *,
    paper_id: str,
    output_dir: Path,
    pdf_path: Path | None = None,
    pdf_url: str | None = None,
    max_pages: int | None = None,
    download_pdf: DownloadPdf | None = None,
) -> dict[str, Any]:
    """
    Parse an arXiv PDF into the benchmark ParsedPaper JSON schema.

    Args:
        paper_id: arXiv identifier, for example "2312.03275".
        output_dir: Directory used for downloaded PDFs.
        pdf_path: Optional local PDF path. When provided, no download is attempted.
        pdf_url: Optional PDF URL. Defaults to https://arxiv.org/pdf/<paper_id>.
        max_pages: Optional page extraction cap passed to the underlying extractor.
        download_pdf: Optional synchronous downloader for tests or custom transports.
    Returns:
        ParsedPaper-compatible mapping with source_type fixed to "pdf".
    """
    source_path = _resolve_pdf_path(paper_id, output_dir, pdf_path)
    warnings: list[str] = []

    if pdf_path is None:
        url = pdf_url or default_pdf_url(paper_id)
        downloader = download_pdf or default_download_pdf
        if not source_path.exists():
            try:
                downloader(url, source_path)
            except Exception as exc:
                return _empty_parsed_paper(
                    paper_id=paper_id,
                    source_path=source_path,
                    availability="failed",
                    warnings=[f"Download failed: {exc}"],
                )

    if not source_path.exists():
        return _empty_parsed_paper(
            paper_id=paper_id,
            source_path=source_path,
            availability="unavailable",
            warnings=[f"PDF source unavailable: {source_path}"],
        )

    try:
        pages = extract_pages_from_pdf(source_path, max_pages=max_pages)
    except Exception as exc:
        return _empty_parsed_paper(
            paper_id=paper_id,
            source_path=source_path,
            availability="failed",
            warnings=[f"PDF parsing failed: {exc}"],
        )

    if not pages:
        warnings.append("PDF parsing produced no page text.")
    return build_parsed_pdf_paper(
        paper_id=paper_id,
        source_path=source_path,
        pages=pages,
        warnings=warnings,
        table_max_pages=max_pages,
    )


def build_parsed_pdf_paper(
    *,
    paper_id: str,
    source_path: Path,
    pages: list[PageText],
    warnings: Optional[list[str]] = None,
    chunk_target_tokens: int = DEFAULT_CHUNK_TARGET_TOKENS,
    chunk_max_tokens: int = DEFAULT_CHUNK_MAX_TOKENS,
    table_max_pages: int | None = None,
) -> dict[str, Any]:
    """
    Build ParsedPaper from already extracted page text.

    Args:
        paper_id: Stable paper id.
        source_path: PDF path used for provenance.
        pages: Extracted pages, in reading order.
        warnings: Parser warnings accumulated before section parsing.
        chunk_target_tokens: Preferred maximum chunk size.
        chunk_max_tokens: Oversized threshold.
    Returns:
        ParsedPaper-compatible mapping.
    """
    parser_warnings = list(warnings or [])
    full_text = _join_pages(pages)
    cleaned_text = _clean_extracted_text(full_text)
    title, sections = _detect_sections(cleaned_text, parser_warnings)
    chunks = _build_chunks(
        sections,
        chunk_target_tokens=chunk_target_tokens,
        chunk_max_tokens=chunk_max_tokens,
    )
    formulas = _extract_formulas(sections)
    tables = _extract_tables(
        sections,
        source_path=source_path,
        warnings=parser_warnings,
        max_pages=table_max_pages,
    )
    figures = _extract_figures(sections)
    references_count = _count_references(sections)
    text_chars = sum(section["char_count"] for section in sections)
    noise_warning_count = _count_noise_warnings(parser_warnings)

    metrics = {
        "section_count": len(sections),
        "table_count": len(tables),
        "figure_caption_count": len(figures),
        "formula_count": len(formulas),
        "display_formula_count": sum(
            1 for formula in formulas if formula["kind"] == "display"
        ),
        "inline_formula_count": sum(
            1 for formula in formulas if formula["kind"] == "inline"
        ),
        "chunk_count": len(chunks),
        "oversized_chunk_count": sum(1 for chunk in chunks if chunk["oversized"]),
        "candidate_numeric_result_count": _count_candidate_numeric_results(cleaned_text),
        "noise_warning_count": noise_warning_count,
        "normalized_section_coverage": _normalized_section_coverage(sections),
    }

    return {
        "paper_id": paper_id,
        "source_type": SOURCE_TYPE,
        "source_path": str(source_path),
        "parser_name": PARSER_NAME,
        "parser_version": PARSER_VERSION,
        "availability": "available",
        "title": title,
        "text_chars": text_chars,
        "sections": sections,
        "chunks": chunks,
        "tables": tables,
        "figures": figures,
        "formulas": formulas,
        "references_count": references_count,
        "warnings": parser_warnings,
        "metrics": metrics,
    }


def write_parsed_pdf_paper(
    *,
    paper_id: str,
    output_dir: Path,
    pdf_path: Path | None = None,
    pdf_url: str | None = None,
    max_pages: int | None = None,
    download_pdf: DownloadPdf | None = None,
) -> Path:
    parsed = parse_pdf_paper(
        paper_id=paper_id,
        output_dir=output_dir,
        pdf_path=pdf_path,
        pdf_url=pdf_url,
        max_pages=max_pages,
        download_pdf=download_pdf,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{paper_id}.pdf.parsed.json"
    output_path.write_text(
        json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def default_pdf_url(paper_id: str) -> str:
    return f"https://arxiv.org/pdf/{paper_id}"


def default_download_pdf(pdf_url: str, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        pdf_url,
        headers={"User-Agent": "RisearchAgent source benchmark"},
    )
    tmp_path = target_path.with_name(f"{target_path.name}.tmp")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            content = response.read()
        if not content:
            raise ValueError(f"Empty PDF response: {pdf_url}")
        tmp_path.write_bytes(content)
        tmp_path.replace(target_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def _empty_parsed_paper(
    *,
    paper_id: str,
    source_path: Path,
    availability: str,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "paper_id": paper_id,
        "source_type": SOURCE_TYPE,
        "source_path": str(source_path),
        "parser_name": PARSER_NAME,
        "parser_version": PARSER_VERSION,
        "availability": availability,
        "title": "",
        "text_chars": 0,
        "sections": [],
        "chunks": [],
        "tables": [],
        "figures": [],
        "formulas": [],
        "references_count": 0,
        "warnings": warnings,
        "metrics": {
            "section_count": 0,
            "table_count": 0,
            "figure_caption_count": 0,
            "formula_count": 0,
            "display_formula_count": 0,
            "inline_formula_count": 0,
            "chunk_count": 0,
            "oversized_chunk_count": 0,
            "candidate_numeric_result_count": 0,
            "noise_warning_count": _count_noise_warnings(warnings),
            "normalized_section_coverage": 0.0,
        },
    }


def _resolve_pdf_path(paper_id: str, output_dir: Path, pdf_path: Path | None) -> Path:
    if pdf_path is not None:
        return pdf_path
    safe_id = paper_id.replace("/", "_")
    return output_dir / "sources" / f"{safe_id}.pdf"


def _join_pages(pages: Iterable[PageText]) -> str:
    return "\n\n".join(page.text for page in pages if page.text.strip())


def _clean_extracted_text(text: str) -> str:
    text = normalize_extracted_text(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def _detect_sections(
    text: str,
    warnings: list[str],
) -> tuple[str, list[dict[str, Any]]]:
    if not text:
        warnings.append("Section detection failed: extracted text is empty.")
        return "", [_section("sec-0001", "Full Text", "other", 1, 0, "")]

    lines = text.splitlines()
    title, title_index = _extract_title(lines)
    heading_positions: list[tuple[int, str, int]] = []
    for index, line in enumerate(lines):
        if index == title_index:
            continue
        heading = _parse_heading(line)
        if heading is None:
            continue
        heading_title, level = heading
        heading_positions.append((index, heading_title, level))

    if not heading_positions:
        warnings.append("Section detection failed: no reliable section headings found.")
        return title, [_section("sec-0001", "Full Text", "other", 1, 0, text)]

    sections: list[dict[str, Any]] = []
    for order, (line_index, heading_title, level) in enumerate(heading_positions):
        next_index = (
            heading_positions[order + 1][0]
            if order + 1 < len(heading_positions)
            else len(lines)
        )
        body = "\n".join(lines[line_index + 1:next_index]).strip()
        section_id = f"sec-{order + 1:04d}"
        sections.append(
            _section(
                section_id,
                heading_title,
                _normalize_section_type(heading_title),
                level,
                order,
                body,
            )
        )

    if len(sections) == 1 and sections[0]["normalized_type"] == "other":
        warnings.append(
            "Section detection low confidence: only one non-canonical heading found."
        )
    return title, sections


def _extract_title(lines: list[str]) -> tuple[str, int | None]:
    for index, raw_line in enumerate(lines[:30]):
        if _is_title_noise_line(raw_line):
            continue
        title = _clean_heading_title(raw_line)
        if not title:
            continue
        if _is_standalone_canonical_heading(title):
            return "", None
        if _looks_like_table_line(title):
            continue
        if len(title) <= 180:
            return title, index
    return "", None


def _is_title_noise_line(raw_line: str) -> bool:
    line = raw_line.strip().strip("*_` ").strip()
    lowered = line.lower()
    if not line:
        return True
    if lowered.startswith(("http://", "https://")):
        return True
    if "intentionally omitted" in lowered or "picture [" in lowered:
        return True
    if re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}$", line):
        return True
    return False


def _parse_heading(line: str) -> tuple[str, int] | None:
    raw = line.strip()
    if not raw or _looks_like_table_line(raw):
        return None
    if len(raw) > 140:
        return None

    markdown = re.match(r"^(#{1,4})\s+(.+?)\s*$", raw)
    if markdown:
        title = _clean_heading_title(markdown.group(2))
        if _is_plausible_heading_title(title):
            return title, len(markdown.group(1))

    exact_title = _clean_heading_title(raw)
    if _is_standalone_canonical_heading(exact_title):
        return exact_title, 1

    numbered = re.match(r"^(\d+(?:\.\d+)*)\.?\s+([A-Z][^.|]{1,120})$", raw)
    if numbered:
        title = _clean_heading_title(numbered.group(2))
        if _is_plausible_heading_title(title):
            return title, numbered.group(1).count(".") + 1

    roman = re.match(r"^([IVX]{1,6})\.\s+([A-Z][^.|]{1,120})$", raw)
    if roman:
        title = _clean_heading_title(roman.group(2))
        if _is_plausible_heading_title(title):
            return title, 1

    appendix = re.match(r"^(Appendix(?:\s+[A-Z])?)(?:[:.\s]+(.+))?$", raw, re.I)
    if appendix:
        suffix = appendix.group(2) or ""
        title = _clean_heading_title(f"{appendix.group(1)} {suffix}".strip())
        return title, 1

    return None


def _clean_heading_title(raw: str) -> str:
    title = raw.strip().strip("#").strip()
    title = re.sub(r"^\[(.+?)\]\(.+?\)$", r"\1", title)
    title = title.strip("*_` ").strip()
    title = re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", title)
    title = re.sub(r"^[IVX]{1,6}\.\s+", "", title, flags=re.I)
    title = title.strip("*_` ").strip()
    return title.strip()


def _looks_like_table_line(line: str) -> bool:
    stripped = line.strip()
    if stripped.startswith("|") and stripped.endswith("|"):
        return True
    return bool(re.match(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$", stripped))


def _is_plausible_heading_title(title: str) -> bool:
    if not title or len(title) > 120:
        return False
    if title.endswith(".") and _normalize_section_type(title) == "other":
        return False
    if len(title.split()) > 16:
        return False
    return True


def _is_standalone_canonical_heading(title: str) -> bool:
    normalized = re.sub(r"[^a-z0-9 ]+", " ", title.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    exact = {
        "abstract",
        "introduction",
        "related work",
        "background",
        "preliminaries",
        "method",
        "methods",
        "methodology",
        "approach",
        "experiments",
        "experimental setup",
        "evaluation",
        "results",
        "discussion",
        "limitations",
        "conclusion",
        "conclusions",
        "references",
        "bibliography",
    }
    if normalized in exact:
        return True
    return bool(re.match(r"^appendix(?: [a-z0-9]+)?$", normalized))


def _normalize_section_type(title: str) -> str:
    normalized = re.sub(r"[^a-z0-9 ]+", " ", title.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if normalized == "abstract":
        return "abstract"
    if "introduction" in normalized:
        return "introduction"
    if "related work" in normalized or "prior work" in normalized:
        return "related_work"
    if "background" in normalized or "preliminar" in normalized:
        return "background"
    if (
        "method" in normalized
        or "approach" in normalized
        or "model" in normalized
        or "architecture" in normalized
    ):
        return "method"
    if (
        "experiment" in normalized
        or "evaluation" in normalized
        or "benchmark" in normalized
        or "empirical" in normalized
    ):
        return "experiments"
    if "result" in normalized or "analysis" in normalized:
        return "results"
    if "discussion" in normalized:
        return "discussion"
    if "limitation" in normalized:
        return "limitations"
    if "conclusion" in normalized or "future work" in normalized:
        return "conclusion"
    if normalized.startswith("appendix") or normalized.startswith("supplement"):
        return "appendix"
    if normalized in {"references", "bibliography"}:
        return "references"
    return "other"


def _section(
    section_id: str,
    title: str,
    normalized_type: str,
    level: int,
    order: int,
    text: str,
) -> dict[str, Any]:
    cleaned_text = text.strip()
    return {
        "section_id": section_id,
        "title": title,
        "normalized_type": normalized_type,
        "level": level,
        "order": order,
        "text": cleaned_text,
        "text_preview": _preview(cleaned_text),
        "char_count": len(cleaned_text),
    }


def _build_chunks(
    sections: list[dict[str, Any]],
    *,
    chunk_target_tokens: int,
    chunk_max_tokens: int,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for section in sections:
        section_text = section["text"]
        pieces = _split_text_for_chunks(section_text, chunk_target_tokens)
        if not pieces:
            pieces = [""]
        for piece in pieces:
            token_estimate = _estimate_tokens(piece)
            chunks.append(
                {
                    "chunk_id": f"chunk-{len(chunks) + 1:04d}",
                    "section_id": section["section_id"],
                    "heading_path": [section["title"]],
                    "normalized_section_type": section["normalized_type"],
                    "text": piece,
                    "text_preview": _preview(piece),
                    "token_estimate": token_estimate,
                    "oversized": token_estimate > chunk_max_tokens,
                    "order": len(chunks),
                }
            )
    return chunks


def _split_text_for_chunks(text: str, target_tokens: int) -> list[str]:
    if _estimate_tokens(text) <= target_tokens:
        return [text] if text else []

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for paragraph in paragraphs:
        paragraph_tokens = _estimate_tokens(paragraph)
        if current and current_tokens + paragraph_tokens > target_tokens:
            chunks.append("\n\n".join(current))
            current = []
            current_tokens = 0
        if paragraph_tokens > target_tokens:
            chunks.extend(_split_long_paragraph(paragraph, target_tokens))
            continue
        current.append(paragraph)
        current_tokens += paragraph_tokens
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _split_long_paragraph(paragraph: str, target_tokens: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for sentence in sentences:
        sentence_tokens = _estimate_tokens(sentence)
        if current and current_tokens + sentence_tokens > target_tokens:
            chunks.append(" ".join(current).strip())
            current = []
            current_tokens = 0
        current.append(sentence)
        current_tokens += sentence_tokens
    if current:
        chunks.append(" ".join(current).strip())
    return chunks


def _extract_formulas(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    formulas: list[dict[str, Any]] = []
    for section in sections:
        occupied_spans: list[tuple[int, int]] = []
        text = section["text"]
        line_start = 0
        for raw_line in text.splitlines():
            line = raw_line.strip()
            line_end = line_start + len(raw_line)
            display = _parse_display_formula(line)
            if display is not None:
                formula_text, label = display
                formulas.append(
                    _formula_record(
                        formula_id=f"formula-{len(formulas) + 1:04d}",
                        section_id=section["section_id"],
                        kind="display",
                        text=formula_text,
                        label=label,
                        order=len(formulas),
                        char_start=line_start,
                        char_end=line_end,
                        section_text=text,
                    )
                )
                occupied_spans.append((line_start, line_end))
            line_start = line_end + 1

        for match in _iter_inline_formula_matches(text, occupied_spans):
            formulas.append(
                _formula_record(
                    formula_id=f"formula-{len(formulas) + 1:04d}",
                    section_id=section["section_id"],
                    kind="inline",
                    text=_clean_formula_text(match.group()),
                    label="",
                    order=len(formulas),
                    char_start=match.start(),
                    char_end=match.end(),
                    section_text=text,
                )
            )
    formulas.sort(key=lambda item: (item["section_id"], item["char_start"], item["kind"]))
    for index, formula in enumerate(formulas, start=1):
        formula["formula_id"] = f"formula-{index:04d}"
        formula["order"] = index - 1
    return formulas


def _parse_display_formula(line: str) -> tuple[str, str] | None:
    if not line or len(line) > 220 or _looks_like_table_line(line):
        return None
    if _is_omitted_picture_placeholder(line):
        return None
    label = ""
    label_match = re.search(r"\s+\(([\w.-]+)\)\s*$", line)
    if label_match:
        label = label_match.group(1)
        line = line[: label_match.start()].strip()
    if not _looks_like_formula_text(line):
        return None
    if len(re.findall(r"[A-Za-z]{4,}", line)) > 3:
        return None
    return _clean_formula_text(line), label


def _iter_inline_formula_matches(
    text: str,
    occupied_spans: list[tuple[int, int]],
) -> Iterable[re.Match[str]]:
    patterns = [
        re.compile(
            r"(?<!\w)(?:[A-Za-z][A-Za-z0-9_]*|[\u0370-\u03FF])\s*=\s*"
            r"[^.,;\n]{1,80}?"
            r"(?=\s+(?:before|after|where|with|for|from|to|then|and|is|are)\b|[.,;]|\n|$)"
        ),
        re.compile(
            r"(?<!\w)[A-Za-z\u0370-\u03FF][A-Za-z0-9_\u0370-\u03FF]*"
            r"\([^)\n]{1,40}\)"
        ),
    ]
    seen: set[tuple[int, int]] = set()
    for pattern in patterns:
        for match in pattern.finditer(text):
            span = match.span()
            if span in seen or _span_overlaps(span, occupied_spans):
                continue
            formula_text = _clean_formula_text(match.group())
            if _looks_like_formula_text(formula_text):
                seen.add(span)
                yield match


def _formula_record(
    *,
    formula_id: str,
    section_id: str,
    kind: str,
    text: str,
    label: str,
    order: int,
    char_start: int,
    char_end: int,
    section_text: str,
) -> dict[str, Any]:
    return {
        "formula_id": formula_id,
        "section_id": section_id,
        "kind": kind,
        "text": text,
        "text_preview": _preview(text),
        "label": label,
        "context_before": _preview(section_text[max(0, char_start - 160):char_start], 160),
        "context_after": _preview(section_text[char_end:char_end + 160], 160),
        "char_start": char_start,
        "char_end": char_end,
        "order": order,
    }


def _span_overlaps(
    span: tuple[int, int],
    occupied_spans: list[tuple[int, int]],
) -> bool:
    start, end = span
    return any(
        start < occupied_end and end > occupied_start
        for occupied_start, occupied_end in occupied_spans
    )


def _looks_like_formula_text(text: str) -> bool:
    compact = text.strip()
    if len(compact) < 3:
        return False
    if _is_omitted_picture_placeholder(compact):
        return False
    math_markers = (
        "\\sum",
        "\\log",
        "\\frac",
        "\\prod",
        "\\math",
        "^",
        "_",
        "=",
        "<=",
        ">=",
        "\u2264",
        "\u2265",
        "\u2208",
        "\u2211",
        "\u220f",
        "|",
    )
    if any(marker in compact for marker in math_markers):
        return True
    return bool(re.search(r"[A-Za-z\u0370-\u03FF]\([^)]*[+\-*/=|][^)]*\)", compact))


def _is_omitted_picture_placeholder(text: str) -> bool:
    lowered = text.lower()
    return "intentionally omitted" in lowered and "picture" in lowered


def _clean_formula_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text.rstrip(".,;:")


def _extract_tables(
    sections: list[dict[str, Any]],
    *,
    source_path: Path,
    warnings: list[str],
    max_pages: int | None,
) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for section in sections:
        lines = section["text"].splitlines()
        for index, line in enumerate(lines):
            caption = _extract_table_caption(lines, index)
            if caption is None:
                continue
            markdown = _collect_markdown_table(lines[index + 1:index + 12])
            if not markdown:
                markdown = "\n".join(lines[index:index + 4]).strip()
            numeric_count = _count_numeric_cells(markdown)
            tables.append(
                {
                    "table_id": f"table-{len(tables) + 1:04d}",
                    "caption": caption,
                    "markdown": markdown,
                    "markdown_preview": _preview(markdown),
                    "numeric_cell_count": numeric_count,
                    "section_id": section["section_id"],
                    "extraction_method": "markdown_caption",
                }
            )
    pdf_tables = _extract_tables_with_pymupdf(
        source_path=source_path,
        sections=sections,
        warnings=warnings,
        max_pages=max_pages,
    )
    return _merge_tables(tables, pdf_tables)


def _extract_table_caption(lines: list[str], index: int) -> str | None:
    caption = _extract_caption(lines[index], "table")
    if caption is not None:
        return caption
    match = re.match(r"^\s*Table\s+(\d+[a-zA-Z]?)\s*[:.]?\s*$", lines[index], re.I)
    if not match:
        return None
    for offset in range(1, 4):
        next_index = index + offset
        if next_index >= len(lines):
            break
        candidate = lines[next_index].strip()
        if not candidate:
            continue
        if _looks_like_table_line(candidate):
            return f"Table {match.group(1)}"
        return f"Table {match.group(1)}: {candidate.rstrip('.') }."
    return f"Table {match.group(1)}"


def _extract_tables_with_pymupdf(
    *,
    source_path: Path,
    sections: list[dict[str, Any]],
    warnings: list[str],
    max_pages: int | None,
) -> list[dict[str, Any]]:
    if not source_path.exists():
        return []
    try:
        import fitz
    except ImportError:
        return []

    try:
        doc = fitz.open(source_path)
    except Exception as exc:
        warnings.append(f"PyMuPDF table fallback could not open PDF: {exc}")
        return []

    tables: list[dict[str, Any]] = []
    try:
        for page_index, page in enumerate(doc, start=1):
            if max_pages is not None and page_index > max_pages:
                break
            try:
                found = page.find_tables()
            except Exception as exc:
                warnings.append(
                    f"PyMuPDF table fallback failed on page {page_index}: {exc}"
                )
                continue
            for table in getattr(found, "tables", []) or []:
                rows = _normalize_table_rows(table.extract())
                if not _table_has_content(rows):
                    continue
                markdown = _rows_to_markdown(rows)
                section = _guess_table_section(sections, page_index)
                caption = _guess_table_caption(section, fallback=f"Table on page {page_index}")
                tables.append(
                    {
                        "table_id": f"table-{len(tables) + 1:04d}",
                        "caption": caption,
                        "markdown": markdown,
                        "markdown_preview": _preview(markdown),
                        "numeric_cell_count": _count_numeric_cells(markdown),
                        "section_id": section["section_id"] if section else "",
                        "extraction_method": "pymupdf_find_tables",
                        "page": page_index,
                        "bbox": list(getattr(table, "bbox", ()) or ()),
                    }
                )
    finally:
        doc.close()
    return tables


def _normalize_table_rows(raw_rows: object) -> list[list[str]]:
    if not isinstance(raw_rows, list):
        return []
    rows: list[list[str]] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, list):
            continue
        rows.append(["" if cell is None else str(cell).strip() for cell in raw_row])
    return rows


def _table_has_content(rows: list[list[str]]) -> bool:
    non_empty_cells = sum(1 for row in rows for cell in row if cell)
    numeric_cells = sum(
        1 for row in rows for cell in row if re.search(r"[-+]?\d+(?:\.\d+)?", cell)
    )
    return non_empty_cells >= 4 and numeric_cells >= 1


def _rows_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    header = normalized[0]
    body = normalized[1:]
    lines = [
        _markdown_row(header),
        _markdown_row(["---"] * width),
    ]
    lines.extend(_markdown_row(row) for row in body)
    return "\n".join(lines)


def _markdown_row(values: list[str]) -> str:
    return "| " + " | ".join(_escape_markdown_cell(value) for value in values) + " |"


def _escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _guess_table_section(
    sections: list[dict[str, Any]],
    page_index: int,
) -> dict[str, Any] | None:
    del page_index
    for section in sections:
        if section["normalized_type"] in {"experiments", "results"}:
            return section
    return sections[0] if sections else None


def _guess_table_caption(section: dict[str, Any] | None, fallback: str) -> str:
    if section is None:
        return fallback
    lines = section["text"].splitlines()
    for index, _line in enumerate(lines):
        caption = _extract_table_caption(lines, index)
        if caption is not None:
            return caption
    return fallback


def _merge_tables(
    text_tables: list[dict[str, Any]],
    pdf_tables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged = list(text_tables)
    for pdf_table in pdf_tables:
        replaced = False
        for index, text_table in enumerate(merged):
            if _same_table_caption(text_table["caption"], pdf_table["caption"]):
                merged[index] = pdf_table
                replaced = True
                break
        if not replaced:
            merged.append(pdf_table)
    for index, table in enumerate(merged, start=1):
        table["table_id"] = f"table-{index:04d}"
    return merged


def _same_table_caption(left: str, right: str) -> bool:
    return _caption_key(left) == _caption_key(right)


def _caption_key(caption: str) -> str:
    match = re.match(r"\s*table\s+(\d+[a-zA-Z]?)", caption, re.I)
    if match:
        return match.group(1).lower()
    return re.sub(r"\W+", " ", caption.lower()).strip()


def _extract_figures(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    figures: list[dict[str, Any]] = []
    for section in sections:
        for line in section["text"].splitlines():
            caption = _extract_caption(line, "figure")
            if caption is None:
                continue
            figures.append(
                {
                    "figure_id": f"figure-{len(figures) + 1:04d}",
                    "caption": caption,
                    "section_id": section["section_id"],
                }
            )
    return figures


def _extract_caption(line: str, kind: str) -> str | None:
    prefix = "Table" if kind == "table" else "Figure|Fig\\."
    match = re.match(rf"^\s*((?:{prefix})\s+\d+[a-zA-Z]?\s*[:.]\s+.+?)\s*$", line, re.I)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _collect_markdown_table(lines: list[str]) -> str:
    table_lines: list[str] = []
    for line in lines:
        if _looks_like_table_line(line):
            table_lines.append(line.strip())
            continue
        if table_lines:
            break
    return "\n".join(table_lines)


def _count_numeric_cells(markdown: str) -> int:
    count = 0
    for raw_line in markdown.splitlines():
        if not raw_line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in raw_line.strip("|").split("|")]
        count += sum(1 for cell in cells if _is_numeric_cell(cell))
    return count


def _is_numeric_cell(cell: str) -> bool:
    normalized = cell.strip()
    if not normalized:
        return False
    return bool(re.fullmatch(r"[-+]?\d+(?:\.\d+)?%?(?:\s*\u00b1\s*\d+(?:\.\d+)?)?", normalized))


def _count_references(sections: list[dict[str, Any]]) -> int:
    reference_sections = [
        section for section in sections if section["normalized_type"] == "references"
    ]
    if not reference_sections:
        return 0
    text = "\n".join(section["text"] for section in reference_sections)
    bracketed = re.findall(r"(?m)^\s*\[\d+\]", text)
    if bracketed:
        return len(bracketed)
    numbered = re.findall(r"(?m)^\s*\d+\.\s+\S", text)
    return len(numbered)


def _count_candidate_numeric_results(text: str) -> int:
    metric_words = (
        "accuracy|acc|f1|map|bleu|rouge|auc|ap|spl|success|score|error|loss|wer|"
        "precision|recall|iou|psnr|fid"
    )
    metric_then_number = re.compile(
        rf"\b(?:{metric_words})\b[^.\n]{{0,80}}[-+]?\d+(?:\.\d+)?%?",
        re.I,
    )
    number_then_metric = re.compile(
        rf"[-+]?\d+(?:\.\d+)?%?[^.\n]{{0,40}}\b(?:{metric_words})\b",
        re.I,
    )
    spans = {match.span() for match in metric_then_number.finditer(text)}
    spans.update(match.span() for match in number_then_metric.finditer(text))
    return len(spans)


def _normalized_section_coverage(sections: list[dict[str, Any]]) -> float:
    if not sections:
        return 0.0
    canonical = sum(1 for section in sections if section["normalized_type"] != "other")
    return round(canonical / len(sections), 4)


def _count_noise_warnings(warnings: list[str]) -> int:
    return sum(
        1
        for warning in warnings
        if any(
            marker in warning.lower()
            for marker in ("noise", "empty", "failed", "low confidence", "unavailable")
        )
    )


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / 4))


def _preview(text: str, limit: int = 500) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact[:limit]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse one arXiv PDF into ParsedPaper benchmark JSON."
    )
    parser.add_argument("--paper-id", required=True, help="arXiv paper id")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--pdf", help="Local PDF path")
    source.add_argument("--pdf-url", help="PDF URL")
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for downloaded PDF and parsed JSON output",
    )
    parser.add_argument("--max-pages", type=int, help="Maximum pages to parse")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output_path = write_parsed_pdf_paper(
        paper_id=args.paper_id,
        output_dir=Path(args.output_dir),
        pdf_path=Path(args.pdf) if args.pdf else None,
        pdf_url=args.pdf_url,
        max_pages=args.max_pages,
    )
    print(output_path)


if __name__ == "__main__":
    main()
