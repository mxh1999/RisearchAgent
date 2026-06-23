from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

PARSER_NAME = "tex_source_parser"
PARSER_VERSION = "0.1.0"
SOURCE_TYPE = "arxiv_tex"


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

    tex_files = list(source_path.rglob("*.tex")) if source_path.is_dir() else []
    if not tex_files and source_path.suffix.lower() != ".tex":
        return _empty_parsed_paper(
            paper_id=paper_id,
            source_path=source_path,
            pdf_path=pdf_path,
            availability="no_tex_entrypoint",
            warnings=[f"No TeX entrypoint found under: {source_path}"],
        )

    return _empty_parsed_paper(
        paper_id=paper_id,
        source_path=source_path,
        pdf_path=pdf_path,
        availability="parse_failed",
        warnings=["Parser skeleton does not extract TeX content yet."],
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
