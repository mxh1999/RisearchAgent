from __future__ import annotations

import argparse
from dataclasses import dataclass
import gzip
import json
import re
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any

PARSER_NAME = "tex_source_parser"
PARSER_VERSION = "0.1.0"
SOURCE_TYPE = "arxiv_tex"
_INPUT_RE = re.compile(r"\\(?:input|include)\s*\{([^{}]+)\}")


@dataclass(frozen=True)
class SourceSegment:
    source_file: Path
    flat_start: int
    flat_end: int
    line_offset: int


@dataclass(frozen=True)
class FlattenedSource:
    text: str
    segments: list[SourceSegment]
    unresolved_input_count: int


def parse_tex_source_paper(
    *,
    paper_id: str,
    source_path: Path,
    pdf_path: Path | None = None,
) -> dict[str, Any]:
    """
    Parse a local TeX source package into a TeX-first evidence JSON schema.

    Args:
        paper_id: Stable paper identifier, usually an arXiv id.
        source_path: Local source archive, source directory, or plain TeX file.
        pdf_path: Optional downloaded PDF path recorded as provenance only.
    Returns:
        Parsed paper mapping with source_type fixed to "arxiv_tex".
    """
    source_path = Path(source_path)
    if not source_path.exists():
        return _empty_parsed_paper(
            paper_id=paper_id,
            source_path=source_path,
            pdf_path=pdf_path,
            availability="unavailable",
            warnings=[f"Source path unavailable: {source_path}"],
        )

    warnings: list[str] = []
    try:
        if source_path.is_dir() or source_path.suffix.lower() == ".tex":
            source_root = source_path if source_path.is_dir() else source_path.parent
            return _parse_materialized_source(
                paper_id=paper_id,
                source_path=source_path,
                source_root=source_root,
                pdf_path=pdf_path,
                warnings=warnings,
            )
        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir) / "source"
            source_root.mkdir()
            _materialize_source(source_path, source_root)
            return _parse_materialized_source(
                paper_id=paper_id,
                source_path=source_path,
                source_root=source_root,
                pdf_path=pdf_path,
                warnings=warnings,
            )
    except Exception as exc:
        return _empty_parsed_paper(
            paper_id=paper_id,
            source_path=source_path,
            pdf_path=pdf_path,
            availability="archive_extract_failed",
            warnings=[f"Source archive extraction failed: {exc}"],
        )


def _empty_parsed_paper(
    *,
    paper_id: str,
    source_path: Path,
    pdf_path: Path | None,
    availability: str,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "paper_id": paper_id,
        "source_type": SOURCE_TYPE,
        "availability": availability,
        "parser_name": PARSER_NAME,
        "parser_version": PARSER_VERSION,
        "source_archive_path": str(source_path),
        "source_root": str(source_path if source_path.is_dir() else source_path.parent),
        "main_tex_file": "",
        "pdf_path": str(pdf_path) if pdf_path is not None else "",
        "title": "",
        "abstract": "",
        "sections": [],
        "tables": [],
        "equations": [],
        "figures": [],
        "citations": [],
        "bibliography": [],
        "warnings": warnings,
        "metrics": _metrics(parse_warning_count=len(warnings)),
    }


def _parse_materialized_source(
    *,
    paper_id: str,
    source_path: Path,
    source_root: Path,
    pdf_path: Path | None,
    warnings: list[str],
) -> dict[str, Any]:
    main_tex_file = (
        source_path if source_path.is_file() and source_path.suffix.lower() == ".tex" else None
    )
    if main_tex_file is None:
        main_tex_file = _choose_main_tex(source_root, warnings)
    if main_tex_file is None:
        return _empty_parsed_paper(
            paper_id=paper_id,
            source_path=source_path,
            pdf_path=pdf_path,
            availability="no_tex_entrypoint",
            warnings=warnings + [f"No TeX entrypoint found under: {source_root}"],
        )

    flattened = _flatten_tex_file(
        path=main_tex_file,
        source_root=source_root,
        warnings=warnings,
        seen=set(),
        flat_offset=0,
    )
    sections = _extract_sections_minimal(
        flattened=flattened,
        main_file=main_tex_file,
        source_root=source_root,
    )
    title = _extract_title(flattened.text)
    return _parsed_paper(
        paper_id=paper_id,
        source_path=source_path,
        source_root=source_root,
        main_tex_file=main_tex_file,
        pdf_path=pdf_path,
        title=title,
        abstract="",
        sections=sections,
        tables=[],
        equations=[],
        figures=[],
        citations=[],
        bibliography=[],
        warnings=warnings,
        unresolved_input_count=flattened.unresolved_input_count,
        partial_environment_count=0,
    )


def _parsed_paper(
    *,
    paper_id: str,
    source_path: Path,
    source_root: Path,
    main_tex_file: Path,
    pdf_path: Path | None,
    title: str,
    abstract: str,
    sections: list[dict[str, Any]],
    tables: list[dict[str, Any]],
    equations: list[dict[str, Any]],
    figures: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    bibliography: list[dict[str, Any]],
    warnings: list[str],
    unresolved_input_count: int,
    partial_environment_count: int,
) -> dict[str, Any]:
    return {
        "paper_id": paper_id,
        "source_type": SOURCE_TYPE,
        "availability": "available",
        "parser_name": PARSER_NAME,
        "parser_version": PARSER_VERSION,
        "source_archive_path": str(source_path),
        "source_root": str(source_root),
        "main_tex_file": _relative_path(main_tex_file, source_root),
        "pdf_path": str(pdf_path) if pdf_path is not None else "",
        "title": title,
        "abstract": abstract,
        "sections": sections,
        "tables": tables,
        "equations": equations,
        "figures": figures,
        "citations": citations,
        "bibliography": bibliography,
        "warnings": warnings,
        "metrics": _metrics(
            section_count=len(sections),
            table_count=len(tables),
            equation_count=len(equations),
            figure_count=len(figures),
            citation_count=len(citations),
            bibliography_entry_count=len(bibliography),
            unresolved_input_count=unresolved_input_count,
            partial_environment_count=partial_environment_count,
            missing_caption_table_count=sum(1 for table in tables if not table.get("caption")),
            missing_label_table_count=sum(1 for table in tables if not table.get("label")),
            parse_warning_count=len(warnings),
        ),
    }


def _metrics(
    *,
    section_count: int = 0,
    table_count: int = 0,
    equation_count: int = 0,
    figure_count: int = 0,
    citation_count: int = 0,
    bibliography_entry_count: int = 0,
    unresolved_input_count: int = 0,
    partial_environment_count: int = 0,
    missing_caption_table_count: int = 0,
    missing_label_table_count: int = 0,
    parse_warning_count: int = 0,
) -> dict[str, int]:
    return {
        "section_count": section_count,
        "table_count": table_count,
        "equation_count": equation_count,
        "figure_count": figure_count,
        "citation_count": citation_count,
        "bibliography_entry_count": bibliography_entry_count,
        "unresolved_input_count": unresolved_input_count,
        "partial_environment_count": partial_environment_count,
        "missing_caption_table_count": missing_caption_table_count,
        "missing_label_table_count": missing_label_table_count,
        "parse_warning_count": parse_warning_count,
    }


def _materialize_source(source_path: Path, target_dir: Path) -> None:
    if tarfile.is_tarfile(source_path):
        with tarfile.open(source_path) as archive:
            _safe_extract_tar(archive, target_dir)
        return
    if zipfile.is_zipfile(source_path):
        with zipfile.ZipFile(source_path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                destination = _safe_destination(target_dir, member.filename)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(member))
        return
    if source_path.suffix.lower() == ".gz":
        output_path = target_dir / source_path.with_suffix("").name
        if output_path.suffix.lower() != ".tex":
            output_path = output_path.with_suffix(".tex")
        output_path.write_bytes(gzip.decompress(source_path.read_bytes()))
        return
    destination = target_dir / source_path.name
    destination.write_bytes(source_path.read_bytes())


def _safe_extract_tar(archive: tarfile.TarFile, target_dir: Path) -> None:
    for member in archive.getmembers():
        if not member.isfile():
            continue
        destination = _safe_destination(target_dir, member.name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        extracted = archive.extractfile(member)
        if extracted is not None:
            destination.write_bytes(extracted.read())


def _safe_destination(target_dir: Path, member_name: str) -> Path:
    destination = (target_dir / member_name).resolve()
    destination.relative_to(target_dir.resolve())
    return destination


def _choose_main_tex(source_root: Path, warnings: list[str]) -> Path | None:
    candidates: list[tuple[int, Path]] = []
    preferred_names = {
        "main.tex": 30,
        "paper.tex": 25,
        "ms.tex": 25,
        "article.tex": 20,
    }
    for path in sorted(source_root.rglob("*.tex")):
        text = _read_text(path)
        score = 0
        if "\\documentclass" in text or "\\documentstyle" in text:
            score += 100
        if "\\begin{document}" in text:
            score += 60
        score += preferred_names.get(path.name.lower(), 0)
        score += min(len(text) // 10000, 20)
        candidates.append((score, path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], -len(str(item[1]))), reverse=True)
    strong = [item for item in candidates if item[0] >= 60]
    if len(strong) > 1:
        warnings.append(
            "Multiple main TeX candidates found; selected "
            f"{_relative_path(strong[0][1], source_root)}."
        )
    return candidates[0][1]


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _flatten_tex_file(
    *,
    path: Path,
    source_root: Path,
    warnings: list[str],
    seen: set[Path],
    flat_offset: int,
) -> FlattenedSource:
    del source_root
    resolved = path.resolve()
    if resolved in seen:
        warnings.append(f"Recursive input skipped: {path}")
        return FlattenedSource(text="", segments=[], unresolved_input_count=0)
    seen.add(resolved)

    text = _strip_comments_preserve_lines(_read_text(path))
    pieces: list[str] = []
    segments: list[SourceSegment] = []
    unresolved_input_count = 0
    cursor = 0
    current_flat = flat_offset
    for match in _INPUT_RE.finditer(text):
        prefix = text[cursor:match.start()]
        if prefix:
            pieces.append(prefix)
            segments.append(
                SourceSegment(
                    source_file=path,
                    flat_start=current_flat,
                    flat_end=current_flat + len(prefix),
                    line_offset=_line_number_for_position(text, cursor),
                )
            )
            current_flat += len(prefix)

        child = _resolve_input_path(path, match.group(1))
        if child is None:
            raw_command = match.group(0)
            warnings.append(f"Unresolved input in {path}: {raw_command}")
            pieces.append(raw_command)
            segments.append(
                SourceSegment(
                    source_file=path,
                    flat_start=current_flat,
                    flat_end=current_flat + len(raw_command),
                    line_offset=_line_number_for_position(text, match.start()),
                )
            )
            current_flat += len(raw_command)
            unresolved_input_count += 1
        else:
            child_flattened = _flatten_tex_file(
                path=child,
                source_root=child.parent,
                warnings=warnings,
                seen=seen,
                flat_offset=current_flat,
            )
            pieces.append(child_flattened.text)
            segments.extend(child_flattened.segments)
            current_flat += len(child_flattened.text)
            unresolved_input_count += child_flattened.unresolved_input_count
        cursor = match.end()

    suffix = text[cursor:]
    if suffix:
        pieces.append(suffix)
        segments.append(
            SourceSegment(
                source_file=path,
                flat_start=current_flat,
                flat_end=current_flat + len(suffix),
                line_offset=_line_number_for_position(text, cursor),
            )
        )
    return FlattenedSource(
        text="".join(pieces),
        segments=segments,
        unresolved_input_count=unresolved_input_count,
    )


def _strip_comments_preserve_lines(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        lines.append(re.sub(r"(?<!\\)%.*", "", line))
    return "\n".join(lines)


def _resolve_input_path(path: Path, raw_name: str) -> Path | None:
    raw = raw_name.strip()
    candidates = [path.parent / raw]
    if Path(raw).suffix == "":
        candidates.insert(0, path.parent / f"{raw}.tex")
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _extract_title(text: str) -> str:
    match = re.search(r"\\title(?:\[[^\]]*\])?\s*\{", text)
    if match is None:
        return ""
    open_pos = text.find("{", match.end() - 1)
    close_pos = _find_matching_brace(text, open_pos)
    if close_pos < 0:
        return ""
    return _clean_latex_text(text[open_pos + 1:close_pos - 1])


def _extract_sections_minimal(
    *,
    flattened: FlattenedSource,
    main_file: Path,
    source_root: Path,
) -> list[dict[str, Any]]:
    text = flattened.text
    matches = list(re.finditer(r"\\section\*?\s*\{", text))
    sections: list[dict[str, Any]] = []
    for order, match in enumerate(matches):
        title_open = text.find("{", match.end() - 1)
        title_close = _find_matching_brace(text, title_open)
        if title_close < 0:
            continue
        next_start = matches[order + 1].start() if order + 1 < len(matches) else len(text)
        title = _clean_latex_text(text[title_open + 1:title_close - 1])
        source_start = 0 if order == 0 else match.start()
        latex_source = text[source_start:next_start].strip()
        plain_text = _clean_latex_text(text[title_close:next_start])
        source_file, line_start = _provenance_for_position(
            flattened=flattened,
            position=match.start(),
            fallback=main_file,
            source_root=source_root,
        )
        _, line_end = _provenance_for_position(
            flattened=flattened,
            position=max(match.start(), next_start - 1),
            fallback=main_file,
            source_root=source_root,
        )
        section_id = f"sec-{order + 1:04d}"
        sections.append(
            {
                "section_id": section_id,
                "title": title,
                "level": 1,
                "normalized_type": _normalize_section_type(title),
                "parent_id": None,
                "order": order,
                "heading_path": [title],
                "latex_source": latex_source,
                "plain_text": plain_text,
                "source_file": source_file,
                "line_start": line_start,
                "line_end": line_end,
            }
        )
    return sections


def _find_matching_brace(text: str, open_pos: int) -> int:
    if open_pos < 0 or open_pos >= len(text) or text[open_pos] != "{":
        return -1
    depth = 0
    index = open_pos
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return -1


def _line_number_for_position(text: str, position: int) -> int:
    return text.count("\n", 0, max(0, position)) + 1


def _provenance_for_position(
    *,
    flattened: FlattenedSource,
    position: int,
    fallback: Path,
    source_root: Path,
) -> tuple[str, int]:
    for segment in flattened.segments:
        if segment.flat_start <= position < segment.flat_end:
            local_prefix = flattened.text[segment.flat_start:position]
            line_number = segment.line_offset + local_prefix.count("\n")
            return _relative_path(segment.source_file, source_root), line_number
    return _relative_path(fallback, source_root), 1


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _normalize_section_type(title: str) -> str:
    normalized = re.sub(r"[^a-z0-9 ]+", " ", title.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if "introduction" in normalized:
        return "introduction"
    if "method" in normalized or "approach" in normalized or "model" in normalized:
        return "method"
    if "experiment" in normalized or "evaluation" in normalized or "benchmark" in normalized:
        return "experiments"
    if "result" in normalized or "analysis" in normalized:
        return "results"
    if "conclusion" in normalized:
        return "conclusion"
    if normalized.startswith("appendix"):
        return "appendix"
    return "other"


def _clean_latex_text(text: str) -> str:
    text = text.replace("~", " ")
    text = re.sub(r"\\(?:textbf|emph|textit|small|large|mathrm|mathbf)\s*\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", "", text)
    text = text.replace(r"\_", "_").replace(r"\%", "%").replace(r"\&", "&")
    text = text.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", text).strip()
