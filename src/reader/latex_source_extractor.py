from __future__ import annotations

import gzip
import re
import tarfile
import tempfile
import zipfile
from pathlib import Path

from src.reader.staged_models import SourceTable


_TABLE_ENV_RE = re.compile(
    r"\\begin\{(?P<env>table\*?|sidewaystable\*?)\}"
    r"(?P<body>.*?)"
    r"\\end\{(?P=env)\}",
    re.DOTALL,
)
_TABULAR_RE = re.compile(
    r"\\begin\{(?P<env>tabular\*?|tabularx|longtable)\}"
    r"(?:\[[^\]]*\])?"
    r"\{[^{}]*\}"
    r"(?P<body>.*?)"
    r"\\end\{(?P=env)\}",
    re.DOTALL,
)
_INPUT_RE = re.compile(r"\\(?:input|include)\{([^{}]+)\}")
_SECTION_RE = re.compile(r"\\(?:section|subsection|subsubsection)\*?\{([^{}]+)\}")
_CAPTION_RE = re.compile(r"\\caption(?:\[[^\]]*\])?\{(?P<text>.*?)\}", re.DOTALL)
_LABEL_RE = re.compile(r"\\label\{([^{}]+)\}")


def extract_tables_from_latex_source(path: Path) -> list[SourceTable]:
    """
    Extract table environments from an arXiv TeX source archive or directory.

    Args:
        path: Source directory, tar/tar.gz/zip archive, gzip-compressed TeX file,
            or plain TeX file.
    Returns:
        Table records with raw LaTeX and best-effort markdown table text.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "source"
        root.mkdir()
        _materialize_source(path, root)
        tex_files = sorted(root.rglob("*.tex"))
        if not tex_files:
            return []

        main_file = _choose_main_tex(tex_files)
        seen: set[Path] = set()
        combined = _read_tex_with_inputs(main_file, seen)
        combined = _strip_comments(combined)
        return _extract_tables(combined, source_path=str(main_file.relative_to(root)))


def _materialize_source(path: Path, target_dir: Path) -> None:
    if path.is_dir():
        for source in path.rglob("*"):
            if source.is_file():
                destination = target_dir / source.relative_to(path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read_bytes())
        return

    if tarfile.is_tarfile(path):
        with tarfile.open(path) as archive:
            _safe_extract_tar(archive, target_dir)
        return

    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                destination = _safe_destination(target_dir, member.filename)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(member))
        return

    if path.suffix == ".gz":
        output_path = target_dir / path.with_suffix("").name
        if output_path.suffix != ".tex":
            output_path = output_path.with_suffix(".tex")
        output_path.write_bytes(gzip.decompress(path.read_bytes()))
        return

    destination = target_dir / path.name
    destination.write_bytes(path.read_bytes())


def _safe_extract_tar(archive: tarfile.TarFile, target_dir: Path) -> None:
    for member in archive.getmembers():
        if not member.isfile():
            continue
        destination = _safe_destination(target_dir, member.name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        extracted = archive.extractfile(member)
        if extracted is None:
            continue
        destination.write_bytes(extracted.read())


def _safe_destination(target_dir: Path, member_name: str) -> Path:
    destination = (target_dir / member_name).resolve()
    destination.relative_to(target_dir.resolve())
    return destination


def _choose_main_tex(tex_files: list[Path]) -> Path:
    for path in tex_files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "\\documentclass" in text:
            return path
    return max(tex_files, key=lambda item: item.stat().st_size)


def _read_tex_with_inputs(path: Path, seen: set[Path]) -> str:
    resolved = path.resolve()
    if resolved in seen:
        return ""
    seen.add(resolved)
    text = path.read_text(encoding="utf-8", errors="ignore")

    def replace_input(match: re.Match[str]) -> str:
        raw_name = match.group(1).strip()
        child = (path.parent / raw_name)
        if child.suffix == "":
            child = child.with_suffix(".tex")
        if not child.exists():
            return match.group(0)
        return _read_tex_with_inputs(child, seen)

    return _INPUT_RE.sub(replace_input, text)


def _strip_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        lines.append(re.sub(r"(?<!\\)%.*", "", line))
    return "\n".join(lines)


def _extract_tables(text: str, source_path: str) -> list[SourceTable]:
    tables: list[SourceTable] = []
    for match in _TABLE_ENV_RE.finditer(text):
        body = match.group(0).strip()
        before = text[: match.start()]
        tables.append(
            SourceTable(
                table_id=f"table-{len(tables) + 1}",
                caption=_clean_latex_text(_extract_first(_CAPTION_RE, body)),
                label=_extract_first(_LABEL_RE, body),
                section=_clean_latex_text(_last_section(before)),
                latex=body,
                markdown=_table_to_markdown(body),
                source_path=source_path,
            )
        )
    return tables


def _extract_first(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    if not match:
        return ""
    if "text" in match.groupdict():
        return match.group("text")
    return match.group(1)


def _last_section(text: str) -> str:
    matches = list(_SECTION_RE.finditer(text))
    return matches[-1].group(1) if matches else ""


def _table_to_markdown(table_latex: str) -> str:
    match = _TABULAR_RE.search(table_latex)
    if not match:
        return ""
    rows = _parse_rows(match.group("body"))
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (width - len(row)) for row in rows]
    header = normalized_rows[0]
    lines = [
        _markdown_row(header),
        _markdown_row(["---"] * width),
    ]
    lines.extend(_markdown_row(row) for row in normalized_rows[1:])
    return "\n".join(lines)


def _parse_rows(body: str) -> list[list[str]]:
    body = _normalize_table_macros(body)
    cleaned = re.sub(
        r"\\(?:toprule|midrule|bottomrule|hline)",
        "",
        body,
    )
    cleaned = re.sub(r"\\(?:cline|cmidrule)(?:\([^)]*\))?\{[^{}]*\}", "", cleaned)
    rows: list[list[str]] = []
    for raw_row in re.split(r"(?<!\\)\\\\", cleaned):
        row = raw_row.strip()
        if not row:
            continue
        cells = [_clean_latex_text(cell) for cell in re.split(r"(?<!\\)&", row)]
        if any(cell for cell in cells):
            rows.append(cells)
    return rows


def _normalize_table_macros(text: str) -> str:
    normalized = text
    normalized = re.sub(
        r"\\multicolumn\{[^{}]+\}\{[^{}]*\}\{\\textbf\{([^{}]*)\}\}",
        r"\1",
        normalized,
    )
    normalized = re.sub(
        r"\\multicolumn\{[^{}]+\}\{[^{}]*\}\{([^{}]*)\}",
        r"\1",
        normalized,
    )
    normalized = re.sub(
        r"\\multirow\{[^{}]+\}\{[^{}]*\}\{([^{}]*)\}",
        r"\1",
        normalized,
    )
    normalized = re.sub(r"\\ding\{51\}", "yes", normalized)
    normalized = re.sub(r"\\ding\{55\}", "no", normalized)
    normalized = re.sub(r"\\pmb\{\$\\checkmark\$\}", "yes", normalized)
    normalized = re.sub(r"\$\\checkmark\$", "yes", normalized)
    return normalized


def _clean_latex_text(text: str) -> str:
    text = text.replace("~", " ")
    text = re.sub(r"\\cite[a-zA-Z]*\{[^{}]*\}", "", text)
    text = re.sub(r"\\(?:textbf|emph|mathbf|mathrm|mathit)\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", "", text)
    text = text.replace(r"\_", "_").replace(r"\%", "%").replace(r"\&", "&")
    text = text.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", text).strip()


def _markdown_row(values: list[str]) -> str:
    return "| " + " | ".join(_escape_markdown_cell(value) for value in values) + " |"


def _escape_markdown_cell(value: str) -> str:
    return value.replace("|", r"\|")
