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
_SECTION_RE = re.compile(
    r"\\(?P<cmd>part|chapter|section|subsection|subsubsection|paragraph|subparagraph)"
    r"\*?\s*\{"
)
_CITE_RE = re.compile(r"\\(?P<cmd>cite\w*)\s*(?:\[[^\]]*\]\s*)*\{(?P<keys>[^{}]+)\}")
_BEGIN_ENV_RE = re.compile(r"\\begin\{([^{}]+)\}")
_LABEL_RE = re.compile(r"\\label\s*\{([^{}]+)\}")
_GRAPHICS_RE = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\s*\{([^{}]+)\}")
_TABLE_ENVS = {
    "table",
    "table*",
    "sidewaystable",
    "sidewaystable*",
    "wraptable",
    "longtable",
}
_TABULAR_ENVS = {"tabular", "tabular*", "tabularx"}
_FIGURE_ENVS = {
    "figure",
    "figure*",
    "wrapfigure",
    "sidewaysfigure",
    "sidewaysfigure*",
}
_EQUATION_ENVS = {
    "equation",
    "equation*",
    "align",
    "align*",
    "gather",
    "gather*",
    "multline",
    "multline*",
}
_KNOWN_ENVS = _TABLE_ENVS | _TABULAR_ENVS | _FIGURE_ENVS | _EQUATION_ENVS
_SECTION_LEVELS = {
    "part": 0,
    "chapter": 0,
    "section": 1,
    "subsection": 2,
    "subsubsection": 3,
    "paragraph": 4,
    "subparagraph": 5,
}


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


@dataclass(frozen=True)
class SourceSpan:
    kind: str
    env_name: str
    start: int
    end: int
    partial: bool = False


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
        try:
            _materialize_source(source_path, source_root)
        except Exception as exc:
            return _empty_parsed_paper(
                paper_id=paper_id,
                source_path=source_path,
                pdf_path=pdf_path,
                availability="archive_extract_failed",
                warnings=[f"Source archive extraction failed: {exc}"],
            )
        return _parse_materialized_source(
            paper_id=paper_id,
            source_path=source_path,
            source_root=source_root,
            pdf_path=pdf_path,
            warnings=warnings,
        )


def write_parsed_tex_source_paper(
    *,
    paper_id: str,
    source_path: Path,
    output_dir: Path,
    pdf_path: Path | None = None,
) -> Path:
    """
    Parse local TeX source and write the JSON artifact.

    Args:
        paper_id: Stable paper identifier, usually an arXiv id.
        source_path: Local source archive, source directory, or plain TeX file.
        output_dir: Directory for the parsed JSON artifact.
        pdf_path: Optional downloaded PDF path recorded as provenance only.
    Returns:
        Path to the written JSON artifact.
    """
    parsed = parse_tex_source_paper(
        paper_id=paper_id,
        source_path=source_path,
        pdf_path=pdf_path,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_id = paper_id.replace("/", "_")
    output_path = output_dir / f"{safe_id}.tex.parsed.json"
    output_path.write_text(
        json.dumps(parsed, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


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
    spans = _find_source_spans(flattened.text, warnings)
    object_spans = [span for span in spans if span.kind in {"table", "equation", "figure"}]
    sections = _extract_sections_minimal(
        flattened=flattened,
        main_file=main_tex_file,
        source_root=source_root,
        object_spans=object_spans,
    )
    title = _extract_title(flattened.text)
    abstract = _extract_abstract(flattened.text)
    tables = _build_tables(
        flattened=flattened,
        source_root=source_root,
        spans=[span for span in spans if span.kind == "table"],
        sections=sections,
    )
    equations = _build_equations(
        flattened=flattened,
        source_root=source_root,
        spans=[span for span in spans if span.kind == "equation"],
        sections=sections,
    )
    figures = _build_figures(
        flattened=flattened,
        source_root=source_root,
        spans=[span for span in spans if span.kind == "figure"],
        sections=sections,
    )
    public_sections = [_public_section(section) for section in sections]
    return _parsed_paper(
        paper_id=paper_id,
        source_path=source_path,
        source_root=source_root,
        main_tex_file=main_tex_file,
        pdf_path=pdf_path,
        title=title,
        abstract=abstract,
        sections=public_sections,
        tables=tables,
        equations=equations,
        figures=figures,
        citations=_extract_citations(flattened.text, sections),
        bibliography=_extract_bibliography(
            flattened_text=flattened.text,
            source_root=source_root,
            main_tex_file=main_tex_file,
        ),
        warnings=warnings,
        unresolved_input_count=flattened.unresolved_input_count,
        partial_environment_count=sum(1 for span in spans if span.partial),
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

        child = _resolve_input_path(path, source_root, match.group(1))
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
                source_root=source_root,
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


def _resolve_input_path(path: Path, source_root: Path, raw_name: str) -> Path | None:
    raw = raw_name.strip()
    candidates = [path.parent / raw, source_root / raw]
    if Path(raw).suffix == "":
        candidates.insert(0, path.parent / f"{raw}.tex")
        candidates.insert(1, source_root / f"{raw}.tex")
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
    object_spans: list[SourceSpan],
) -> list[dict[str, Any]]:
    text = flattened.text
    matches = list(_SECTION_RE.finditer(text))
    sections: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    for order, match in enumerate(matches):
        command = match.group("cmd")
        level = _SECTION_LEVELS[command]
        title_open = text.find("{", match.end() - 1)
        title_close = _find_matching_brace(text, title_open)
        if title_close < 0:
            continue
        next_start = matches[order + 1].start() if order + 1 < len(matches) else len(text)
        title = _clean_latex_text(text[title_open + 1:title_close - 1])
        source_start = match.start()
        latex_source = text[source_start:next_start].strip()
        body_text = _remove_spans(
            text=text,
            start=title_close,
            end=next_start,
            spans=object_spans,
        )
        plain_text = _clean_latex_text(body_text)
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
        section_label = _extract_label(text[title_close:next_start])
        section_id = section_label or f"sec-{order + 1:04d}"
        while stack and int(stack[-1]["level"]) >= level:
            stack.pop()
        parent_id = str(stack[-1]["section_id"]) if stack else None
        heading_path = [str(item["title"]) for item in stack] + [title]
        appendix = _is_appendix_section(text, match.start(), title)
        normalized_type = "appendix" if appendix else _normalize_section_type(title)
        section = {
            "section_id": section_id,
            "title": title,
            "level": level,
            "normalized_type": normalized_type,
            "parent_id": parent_id,
            "order": order,
            "heading_path": heading_path,
            "latex_source": latex_source,
            "plain_text": plain_text,
            "source_file": source_file,
            "line_start": line_start,
            "line_end": line_end,
            "_span_start": match.start(),
            "_span_end": next_start,
        }
        sections.append(
            section
        )
        stack.append(section)
    return sections


def _is_appendix_section(text: str, section_start: int, title: str) -> bool:
    appendix_position = text.find(r"\appendix")
    if appendix_position >= 0 and appendix_position < section_start:
        return True
    normalized_title = title.strip().lower()
    return normalized_title.startswith(("appendix", "supplement"))


def _public_section(section: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in section.items()
        if not key.startswith("_")
    }


def _find_source_spans(text: str, warnings: list[str]) -> list[SourceSpan]:
    env_spans = _find_environment_spans(text, warnings)
    display_spans = _find_display_math_spans(text)
    table_containers = [
        span for span in env_spans if span.env_name in _TABLE_ENVS
    ]
    spans: list[SourceSpan] = []
    for span in env_spans:
        if span.env_name in _TABLE_ENVS:
            spans.append(SourceSpan("table", span.env_name, span.start, span.end, span.partial))
        elif span.env_name in _TABULAR_ENVS:
            if not _is_contained_by(span, table_containers):
                spans.append(
                    SourceSpan("table", span.env_name, span.start, span.end, span.partial)
                )
        elif span.env_name in _FIGURE_ENVS:
            spans.append(SourceSpan("figure", span.env_name, span.start, span.end, span.partial))
        elif span.env_name in _EQUATION_ENVS:
            spans.append(
                SourceSpan("equation", span.env_name, span.start, span.end, span.partial)
            )
    spans.extend(display_spans)
    return sorted(spans, key=lambda item: item.start)


def _find_environment_spans(text: str, warnings: list[str]) -> list[SourceSpan]:
    spans: list[SourceSpan] = []
    for match in _BEGIN_ENV_RE.finditer(text):
        env_name = match.group(1)
        if env_name not in _KNOWN_ENVS:
            continue
        end_pattern = re.compile(r"\\end\{" + re.escape(env_name) + r"\}")
        end_match = end_pattern.search(text, match.end())
        if end_match is None:
            warnings.append(f"Partial environment parsed: {env_name}")
            spans.append(
                SourceSpan(
                    kind="environment",
                    env_name=env_name,
                    start=match.start(),
                    end=min(len(text), match.end() + 2000),
                    partial=True,
                )
            )
            continue
        spans.append(
            SourceSpan(
                kind="environment",
                env_name=env_name,
                start=match.start(),
                end=end_match.end(),
            )
        )
    return spans


def _find_display_math_spans(text: str) -> list[SourceSpan]:
    spans: list[SourceSpan] = []
    for match in re.finditer(r"\\\[", text):
        end_match = re.search(r"\\\]", text[match.end():])
        if end_match is not None:
            spans.append(
                SourceSpan(
                    kind="equation",
                    env_name=r"\[",
                    start=match.start(),
                    end=match.end() + end_match.end(),
                )
            )
    dollar_positions = [match.start() for match in re.finditer(r"(?<!\\)\$\$", text)]
    for start, end in zip(dollar_positions[0::2], dollar_positions[1::2]):
        spans.append(SourceSpan(kind="equation", env_name="$$", start=start, end=end + 2))
    return spans


def _is_contained_by(span: SourceSpan, containers: list[SourceSpan]) -> bool:
    return any(
        container.start <= span.start and span.end <= container.end
        for container in containers
    )


def _remove_spans(
    *,
    text: str,
    start: int,
    end: int,
    spans: list[SourceSpan],
) -> str:
    pieces: list[str] = []
    cursor = start
    for span in sorted(spans, key=lambda item: item.start):
        if span.end <= start or span.start >= end:
            continue
        span_start = max(start, span.start)
        span_end = min(end, span.end)
        if cursor < span_start:
            pieces.append(text[cursor:span_start])
        cursor = max(cursor, span_end)
    if cursor < end:
        pieces.append(text[cursor:end])
    return "".join(pieces)


def _build_tables(
    *,
    flattened: FlattenedSource,
    source_root: Path,
    spans: list[SourceSpan],
    sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    for index, span in enumerate(spans, start=1):
        latex_source = flattened.text[span.start:span.end]
        caption = _extract_caption(latex_source)
        label = _extract_label(latex_source)
        source_file, line_start = _provenance_for_position(
            flattened=flattened,
            position=span.start,
            fallback=Path(""),
            source_root=source_root,
        )
        _, line_end = _provenance_for_position(
            flattened=flattened,
            position=max(span.start, span.end - 1),
            fallback=Path(""),
            source_root=source_root,
        )
        table_id = label or f"table-{index:04d}"
        tables.append(
            {
                "table_id": table_id,
                "caption": caption,
                "label": label,
                "section_id": _section_id_for_position(sections, span.start),
                "latex_source": latex_source,
                "source_file": source_file,
                "line_start": line_start,
                "line_end": line_end,
                "references": [],
                "quality_flags": _quality_flags_for_latex(
                    kind="table",
                    env_name=span.env_name,
                    latex_source=latex_source,
                    caption=caption,
                    label=label,
                ),
            }
        )
    return tables


def _build_equations(
    *,
    flattened: FlattenedSource,
    source_root: Path,
    spans: list[SourceSpan],
    sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    equations: list[dict[str, Any]] = []
    for index, span in enumerate(spans, start=1):
        latex_source = flattened.text[span.start:span.end]
        label = _extract_label(latex_source)
        source_file, line_start = _provenance_for_position(
            flattened=flattened,
            position=span.start,
            fallback=Path(""),
            source_root=source_root,
        )
        _, line_end = _provenance_for_position(
            flattened=flattened,
            position=max(span.start, span.end - 1),
            fallback=Path(""),
            source_root=source_root,
        )
        equations.append(
            {
                "equation_id": label or f"equation-{index:04d}",
                "label": label,
                "section_id": _section_id_for_position(sections, span.start),
                "latex_source": latex_source,
                "source_file": source_file,
                "line_start": line_start,
                "line_end": line_end,
                "references": [],
                "quality_flags": [],
            }
        )
    return equations


def _build_figures(
    *,
    flattened: FlattenedSource,
    source_root: Path,
    spans: list[SourceSpan],
    sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    figures: list[dict[str, Any]] = []
    for index, span in enumerate(spans, start=1):
        latex_source = flattened.text[span.start:span.end]
        caption = _extract_caption(latex_source)
        label = _extract_label(latex_source)
        source_file, line_start = _provenance_for_position(
            flattened=flattened,
            position=span.start,
            fallback=Path(""),
            source_root=source_root,
        )
        _, line_end = _provenance_for_position(
            flattened=flattened,
            position=max(span.start, span.end - 1),
            fallback=Path(""),
            source_root=source_root,
        )
        figures.append(
            {
                "figure_id": label or f"figure-{index:04d}",
                "caption": caption,
                "label": label,
                "section_id": _section_id_for_position(sections, span.start),
                "latex_source": latex_source,
                "graphics_paths": _extract_graphics_paths(latex_source),
                "source_file": source_file,
                "line_start": line_start,
                "line_end": line_end,
                "quality_flags": _quality_flags_for_latex(
                    kind="figure",
                    env_name=span.env_name,
                    latex_source=latex_source,
                    caption=caption,
                    label=label,
                ),
            }
        )
    return figures


def _section_id_for_position(sections: list[dict[str, Any]], position: int) -> str:
    if not sections:
        return ""
    if position < int(sections[0]["_span_start"]):
        return ""
    for section in sections:
        if section["_span_start"] <= position < section["_span_end"]:
            return str(section["section_id"])
    return str(sections[-1]["section_id"])


def _extract_caption(latex_source: str) -> str:
    match = re.search(r"\\caption(?:of\{(?:figure|table)\})?(?:\[[^\]]*\])?\s*\{", latex_source)
    if match is None:
        return ""
    open_pos = latex_source.find("{", match.end() - 1)
    close_pos = _find_matching_brace(latex_source, open_pos)
    if close_pos < 0:
        return ""
    return _clean_latex_text(latex_source[open_pos + 1:close_pos - 1])


def _extract_label(latex_source: str) -> str:
    match = _LABEL_RE.search(latex_source)
    return match.group(1).strip() if match else ""


def _extract_graphics_paths(latex_source: str) -> list[str]:
    return [match.group(1).strip() for match in _GRAPHICS_RE.finditer(latex_source)]


def _quality_flags_for_latex(
    *,
    kind: str,
    env_name: str,
    latex_source: str,
    caption: str,
    label: str,
) -> list[str]:
    flags: list[str] = []
    if kind in {"table", "figure"} and not caption:
        flags.append("caption_missing")
    if kind in {"table", "figure"} and not label:
        flags.append("label_missing")
    if kind == "table" and env_name in _TABULAR_ENVS:
        flags.append("orphan_tabular")
    if "\\multicolumn" in latex_source:
        flags.append("has_multicolumn")
    if "\\multirow" in latex_source:
        flags.append("has_multirow")
    if "\\resizebox" in latex_source or "\\scalebox" in latex_source:
        flags.append("has_resizebox")
    if "\\adjustbox" in latex_source or "\\begin{adjustbox}" in latex_source:
        flags.append("has_adjustbox")
    if kind == "table" and len(re.findall(r"\\begin\{tabular\*?|\\begin\{tabularx\}", latex_source)) > 1:
        flags.append("has_nested_tabular")
    if kind == "table" and re.search(r"(?<!\\)\$|\\\(|\\\[", latex_source):
        flags.append("has_math")
    return flags


def _extract_abstract(text: str) -> str:
    match = re.search(r"\\begin\{abstract\}", text)
    if match is None:
        return ""
    end_match = re.search(r"\\end\{abstract\}", text[match.end():])
    if end_match is None:
        return ""
    raw = text[match.end():match.end() + end_match.start()]
    return _compact_latex_whitespace(raw)


def _extract_citations(text: str, sections: list[dict[str, Any]]) -> list[dict[str, str]]:
    citations: list[dict[str, str]] = []
    for match in _CITE_RE.finditer(text):
        command = match.group("cmd")
        for key in match.group("keys").split(","):
            normalized_key = key.strip()
            if not normalized_key:
                continue
            citations.append(
                {
                    "key": normalized_key,
                    "command": command,
                    "section_id": _section_id_for_position(sections, match.start()),
                }
            )
    return citations


def _extract_bibliography(
    *,
    flattened_text: str,
    source_root: Path,
    main_tex_file: Path,
) -> list[dict[str, str]]:
    bibliography: list[dict[str, str]] = []
    bibliography.extend(
        _extract_bibitems_from_text(
            text=flattened_text,
            source_file=_relative_path(main_tex_file, source_root),
        )
    )
    seen_keys = {entry["key"] for entry in bibliography}
    for bbl_path in _candidate_bbl_files(flattened_text, source_root, main_tex_file):
        for entry in _extract_bibitems_from_text(
            text=_read_text(bbl_path),
            source_file=_relative_path(bbl_path, source_root),
        ):
            if entry["key"] in seen_keys:
                continue
            bibliography.append(entry)
            seen_keys.add(entry["key"])
    return bibliography


def _candidate_bbl_files(
    flattened_text: str,
    source_root: Path,
    main_tex_file: Path,
) -> list[Path]:
    candidates: list[Path] = []
    main_bbl = main_tex_file.with_suffix(".bbl")
    if main_bbl.exists():
        candidates.append(main_bbl)
    for match in re.finditer(r"\\bibliography\s*\{([^{}]+)\}", flattened_text):
        for raw_name in match.group(1).split(","):
            name = raw_name.strip()
            if not name:
                continue
            path = source_root / name
            if path.suffix.lower() != ".bbl":
                path = path.with_suffix(".bbl")
            if path.exists():
                candidates.append(path)
    candidates.extend(sorted(source_root.rglob("*.bbl")))
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved not in seen and path.exists():
            unique.append(path)
            seen.add(resolved)
    return unique


def _extract_bibitems_from_text(text: str, source_file: str) -> list[dict[str, str]]:
    matches = list(re.finditer(r"\\bibitem(?:\[[^\]]*\])?\s*\{([^{}]+)\}", text))
    entries: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        raw_text = text[match.end():end]
        raw_text = re.sub(r"\\end\{thebibliography\}.*$", "", raw_text, flags=re.DOTALL)
        entries.append(
            {
                "key": match.group(1).strip(),
                "raw_text": _compact_latex_whitespace(raw_text),
                "source_file": source_file,
            }
        )
    return entries


def _compact_latex_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse one local arXiv TeX source package into JSON."
    )
    parser.add_argument("--paper-id", required=True, help="Paper identifier")
    parser.add_argument(
        "--source",
        required=True,
        help="Local source archive, extracted source directory, or TeX file",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for parsed JSON output",
    )
    parser.add_argument(
        "--pdf",
        help="Optional local PDF path recorded as provenance only",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    output_path = write_parsed_tex_source_paper(
        paper_id=args.paper_id,
        source_path=Path(args.source),
        output_dir=Path(args.output_dir),
        pdf_path=Path(args.pdf) if args.pdf else None,
    )
    print(output_path)


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


if __name__ == "__main__":
    main()
