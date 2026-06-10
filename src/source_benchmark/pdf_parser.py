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
    )


def build_parsed_pdf_paper(
    *,
    paper_id: str,
    source_path: Path,
    pages: list[PageText],
    warnings: Optional[list[str]] = None,
    chunk_target_tokens: int = DEFAULT_CHUNK_TARGET_TOKENS,
    chunk_max_tokens: int = DEFAULT_CHUNK_MAX_TOKENS,
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
    tables = _extract_tables(sections)
    figures = _extract_figures(sections)
    references_count = _count_references(sections)
    text_chars = sum(section["char_count"] for section in sections)
    noise_warning_count = _count_noise_warnings(parser_warnings)

    metrics = {
        "section_count": len(sections),
        "table_count": len(tables),
        "figure_caption_count": len(figures),
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
        "references_count": 0,
        "warnings": warnings,
        "metrics": {
            "section_count": 0,
            "table_count": 0,
            "figure_caption_count": 0,
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


def _extract_tables(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for section in sections:
        lines = section["text"].splitlines()
        for index, line in enumerate(lines):
            caption = _extract_caption(line, "table")
            if caption is None:
                continue
            markdown = _collect_markdown_table(lines[index + 1:index + 8])
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
                }
            )
    return tables


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
        count += sum(1 for cell in cells if re.search(r"[-+]?\d+(?:\.\d+)?", cell))
    return count


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
