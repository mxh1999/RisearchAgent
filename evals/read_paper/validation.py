"""Validate read-paper evaluation manifests and reference cases."""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path
from typing import Any

import yaml


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVIEW_STATUSES = {"draft", "reviewed", "rejected"}
_EVIDENCE_SOURCES = {"pdf", "tex"}


def _load_yaml(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Expected a mapping in {path}")
    return raw


def _find_repository_root(path: Path) -> Path:
    for parent in (path.resolve(), *path.resolve().parents):
        if (parent / ".git").exists() or (parent / "AGENTS.md").exists():
            return parent
    raise ValueError(f"Cannot locate repository root from {path}")


def _require_fields(
    value: dict[str, Any],
    fields: tuple[str, ...],
    location: str,
    errors: list[str],
) -> None:
    for field in fields:
        if field not in value or value[field] is None:
            errors.append(f"{location}: missing required field '{field}'")


def _validate_unique_ids(
    items: Any,
    location: str,
    errors: list[str],
) -> set[str]:
    if not isinstance(items, list):
        errors.append(f"{location}: expected a list")
        return set()

    ids: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"{location}[{index}]: expected a mapping")
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            errors.append(f"{location}[{index}]: missing non-empty id")
        elif item_id in ids:
            errors.append(f"{location}: duplicate id '{item_id}'")
        else:
            ids.add(item_id)
    return ids


def _validate_evidence(
    case: dict[str, Any],
    case_path: Path,
    errors: list[str],
) -> set[str]:
    paper = case.get("paper", {})
    page_count = paper.get("pdf", {}).get("page_count")
    evidence = case.get("reference", {}).get("evidence", [])
    evidence_ids = _validate_unique_ids(evidence, f"{case_path}: evidence", errors)

    for item in evidence if isinstance(evidence, list) else []:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id", "<unknown>")
        source = item.get("source")
        if source not in _EVIDENCE_SOURCES:
            errors.append(
                f"{case_path}: evidence '{item_id}' has invalid source '{source}'"
            )
            continue
        if source == "pdf":
            page = item.get("page")
            if not isinstance(page, int) or isinstance(page, bool) or page < 1:
                errors.append(
                    f"{case_path}: PDF evidence '{item_id}' needs a 1-indexed page"
                )
            elif isinstance(page_count, int) and page > page_count:
                errors.append(
                    f"{case_path}: PDF evidence '{item_id}' exceeds page count"
                )
        else:
            _require_fields(
                item,
                ("file", "line_start", "line_end"),
                f"{case_path}: TeX evidence '{item_id}'",
                errors,
            )
            start = item.get("line_start")
            end = item.get("line_end")
            if (
                not isinstance(start, int)
                or isinstance(start, bool)
                or not isinstance(end, int)
                or isinstance(end, bool)
                or start < 1
                or end < start
            ):
                errors.append(
                    f"{case_path}: TeX evidence '{item_id}' has invalid line range"
                )
    return evidence_ids


def _validate_reference_list(
    items: Any,
    name: str,
    minimum: int,
    evidence_ids: set[str],
    case_path: Path,
    errors: list[str],
) -> None:
    ids = _validate_unique_ids(items, f"{case_path}: {name}", errors)
    if len(ids) < minimum:
        errors.append(
            f"{case_path}: {name} needs at least {minimum} uniquely identified items"
        )
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id", "<unknown>")
        refs = item.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            errors.append(f"{case_path}: {name} '{item_id}' needs evidence_refs")
            continue
        unknown = sorted(set(refs) - evidence_ids)
        if unknown:
            errors.append(
                f"{case_path}: {name} '{item_id}' has unknown evidence refs {unknown}"
            )


def _validate_experiments(
    items: Any,
    evidence_ids: set[str],
    case_path: Path,
    errors: list[str],
) -> None:
    ids = _validate_unique_ids(items, f"{case_path}: experiment_records", errors)
    if len(ids) < 8:
        errors.append(f"{case_path}: experiment_records needs at least 8 items")

    required = (
        "method",
        "method_role",
        "task",
        "benchmark",
        "dataset",
        "split",
        "metric",
        "value",
        "unit",
        "higher_is_better",
        "result_kind",
        "header_path",
        "evidence_refs",
        "critical",
    )
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id", "<unknown>")
        location = f"{case_path}: experiment '{item_id}'"
        _require_fields(item, required, location, errors)
        value = item.get("value")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(f"{location}: value must be numeric")
        if not isinstance(item.get("higher_is_better"), bool):
            errors.append(f"{location}: higher_is_better must be boolean")
        if not isinstance(item.get("critical"), bool):
            errors.append(f"{location}: critical must be boolean")

        header_path = item.get("header_path")
        if not isinstance(header_path, dict):
            errors.append(f"{location}: header_path must be a mapping")
        else:
            for axis in ("row", "column"):
                path = header_path.get(axis)
                if not isinstance(path, list) or not path:
                    errors.append(f"{location}: header_path.{axis} must be non-empty")

        refs = item.get("evidence_refs")
        if isinstance(refs, list):
            unknown = sorted(set(refs) - evidence_ids)
            if unknown:
                errors.append(f"{location}: unknown evidence refs {unknown}")


def _validate_case(
    case: dict[str, Any],
    case_path: Path,
    require_reviewed: bool,
    errors: list[str],
) -> None:
    _require_fields(
        case,
        ("schema_version", "case_id", "review", "paper", "task", "reference"),
        str(case_path),
        errors,
    )
    review = case.get("review", {})
    status = review.get("status")
    if status not in _REVIEW_STATUSES:
        errors.append(f"{case_path}: invalid review status '{status}'")
    if require_reviewed and status != "reviewed":
        errors.append(f"{case_path}: review status is '{status}', expected 'reviewed'")
    if status == "reviewed":
        _require_fields(
            review,
            ("human_reviewer", "reviewed_at"),
            f"{case_path}: review",
            errors,
        )

    paper = case.get("paper", {})
    _require_fields(
        paper,
        ("arxiv_id", "version", "title", "pdf"),
        f"{case_path}: paper",
        errors,
    )
    pdf = paper.get("pdf", {})
    _require_fields(
        pdf,
        ("url", "local_path", "sha256", "page_count"),
        f"{case_path}: paper.pdf",
        errors,
    )
    sha256 = pdf.get("sha256")
    if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
        errors.append(f"{case_path}: paper.pdf.sha256 must be lowercase SHA256")
    page_count = pdf.get("page_count")
    if not isinstance(page_count, int) or isinstance(page_count, bool) or page_count < 1:
        errors.append(f"{case_path}: paper.pdf.page_count must be positive")

    allowed_sources = case.get("task", {}).get("allowed_sources")
    if not isinstance(allowed_sources, list) or not allowed_sources:
        errors.append(f"{case_path}: task.allowed_sources must be non-empty")
    elif not set(allowed_sources).issubset(_EVIDENCE_SOURCES):
        errors.append(f"{case_path}: task.allowed_sources contains invalid values")

    evidence_ids = _validate_evidence(case, case_path, errors)
    reference = case.get("reference", {})
    _validate_reference_list(
        reference.get("claims"),
        "claims",
        3,
        evidence_ids,
        case_path,
        errors,
    )
    _validate_reference_list(
        reference.get("method_components"),
        "method_components",
        3,
        evidence_ids,
        case_path,
        errors,
    )
    _validate_experiments(
        reference.get("experiment_records"), evidence_ids, case_path, errors
    )
    _validate_reference_list(
        reference.get("limitations"),
        "limitations",
        2,
        evidence_ids,
        case_path,
        errors,
    )
    _validate_reference_list(
        reference.get("ambiguities"),
        "ambiguities",
        2,
        evidence_ids,
        case_path,
        errors,
    )

    coverage = reference.get("coverage", {})
    required_areas = coverage.get("required_areas")
    if not isinstance(required_areas, list) or not required_areas:
        errors.append(f"{case_path}: coverage.required_areas must be non-empty")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_asset(
    asset: dict[str, Any],
    location: str,
    repository_root: Path,
    errors: list[str],
) -> None:
    local_path = asset.get("local_path")
    expected_hash = asset.get("sha256")
    if not isinstance(local_path, str) or not local_path:
        errors.append(f"{location}: missing local_path")
        return
    if not isinstance(expected_hash, str) or not _SHA256_RE.fullmatch(expected_hash):
        errors.append(f"{location}: invalid sha256")
        return
    path = repository_root / local_path
    if not path.is_file():
        errors.append(f"{location}: asset does not exist at {path}")
        return
    actual_hash = _sha256(path)
    if actual_hash != expected_hash:
        errors.append(
            f"{location}: SHA256 mismatch, expected {expected_hash}, got {actual_hash}"
        )


def _normalize_source_text(value: str) -> str:
    value = value.replace("\u00ad", "")
    value = re.sub(r"[-\u2010\u2011]\s*\r?\n\s*", "", value)
    value = re.sub(r"(?<=\w)[-\u2010\u2011](?=\w)", "", value)
    return " ".join(value.split()).casefold()


def _validate_evidence_anchors(
    case: dict[str, Any],
    case_path: Path,
    repository_root: Path,
    errors: list[str],
) -> None:
    paper = case.get("paper", {})
    pdf = paper.get("pdf", {})
    pdf_path = repository_root / str(pdf.get("local_path", ""))
    evidence = case.get("reference", {}).get("evidence", [])

    try:
        import fitz
    except ImportError:
        errors.append(f"{case_path}: PyMuPDF is required for PDF anchor validation")
        return

    document = None
    if pdf_path.is_file():
        document = fitz.open(pdf_path)
        expected_pages = pdf.get("page_count")
        if isinstance(expected_pages, int) and document.page_count != expected_pages:
            errors.append(
                f"{case_path}: PDF page count mismatch, expected {expected_pages}, "
                f"got {document.page_count}"
            )

    tex = paper.get("tex", {})
    tex_root_value = tex.get("source_root") if isinstance(tex, dict) else None
    tex_root = (
        (repository_root / tex_root_value).resolve()
        if isinstance(tex_root_value, str)
        else None
    )

    try:
        for item in evidence if isinstance(evidence, list) else []:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id", "<unknown>")
            anchor = item.get("anchor")
            if not isinstance(anchor, str) or not anchor.strip():
                errors.append(f"{case_path}: evidence '{item_id}' needs an anchor")
                continue

            if item.get("source") == "pdf":
                page = item.get("page")
                if document is None or not isinstance(page, int):
                    continue
                page_text = document[page - 1].get_text()
                if _normalize_source_text(anchor) not in _normalize_source_text(
                    page_text
                ):
                    errors.append(
                        f"{case_path}: PDF evidence '{item_id}' anchor not found "
                        f"on page {page}"
                    )
                continue

            if item.get("source") != "tex" or tex_root is None:
                continue
            source_path = (tex_root / str(item.get("file", ""))).resolve()
            if not source_path.is_relative_to(tex_root):
                errors.append(
                    f"{case_path}: TeX evidence '{item_id}' escapes source root"
                )
                continue
            if not source_path.is_file():
                errors.append(
                    f"{case_path}: TeX evidence '{item_id}' file does not exist"
                )
                continue
            lines = source_path.read_text(encoding="utf-8").splitlines()
            start = item.get("line_start")
            end = item.get("line_end")
            if not isinstance(start, int) or not isinstance(end, int):
                continue
            if end > len(lines):
                errors.append(
                    f"{case_path}: TeX evidence '{item_id}' exceeds file length"
                )
                continue
            span = "\n".join(lines[start - 1 : end])
            if _normalize_source_text(anchor) not in _normalize_source_text(span):
                errors.append(
                    f"{case_path}: TeX evidence '{item_id}' anchor not found in span"
                )
    finally:
        if document is not None:
            document.close()


def _validate_rubric(path: Path, errors: list[str]) -> None:
    if not path.is_file():
        errors.append(f"Rubric does not exist: {path}")
        return
    rubric = _load_yaml(path)
    dimensions = rubric.get("dimensions")
    if not isinstance(dimensions, list) or not dimensions:
        errors.append(f"{path}: dimensions must be a non-empty list")
        return
    points = [item.get("points") for item in dimensions if isinstance(item, dict)]
    if any(not isinstance(value, int) for value in points) or sum(points) != 100:
        errors.append(f"{path}: dimension points must be integers summing to 100")
    if not rubric.get("hard_failures"):
        errors.append(f"{path}: hard_failures must be non-empty")
    if not rubric.get("quality_gates"):
        errors.append(f"{path}: quality_gates must be non-empty")


def validate_corpus(
    manifest_path: str | Path,
    *,
    check_assets: bool = False,
    require_reviewed: bool = False,
) -> list[str]:
    """Validate one corpus manifest and its referenced cases.

    Args:
        manifest_path: Corpus manifest path.
        check_assets: Whether to hash local PDF and TeX assets.
        require_reviewed: Whether every case must have human review status.
    Returns:
        Validation errors. An empty list means validation succeeded.
    """
    path = Path(manifest_path).resolve()
    errors: list[str] = []
    if not path.is_file():
        return [f"Manifest does not exist: {path}"]

    manifest = _load_yaml(path)
    _require_fields(
        manifest,
        ("schema_version", "corpus_id", "status", "rubric", "cases"),
        str(path),
        errors,
    )
    rubric_path = (path.parent / str(manifest.get("rubric", ""))).resolve()
    _validate_rubric(rubric_path, errors)

    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append(f"{path}: cases must be a non-empty list")
        return errors

    case_ids: set[str] = set()
    repository_root = _find_repository_root(path)
    for index, entry in enumerate(cases):
        if not isinstance(entry, dict):
            errors.append(f"{path}: cases[{index}] must be a mapping")
            continue
        case_id = entry.get("case_id")
        case_file = entry.get("file")
        if not isinstance(case_id, str) or not case_id:
            errors.append(f"{path}: cases[{index}] needs case_id")
            continue
        if case_id in case_ids:
            errors.append(f"{path}: duplicate case_id '{case_id}'")
        case_ids.add(case_id)
        if not isinstance(case_file, str) or not case_file:
            errors.append(f"{path}: case '{case_id}' needs file")
            continue
        case_path = (path.parent / case_file).resolve()
        if not case_path.is_file():
            errors.append(f"{path}: case file does not exist: {case_path}")
            continue
        case = _load_yaml(case_path)
        if case.get("case_id") != case_id:
            errors.append(
                f"{case_path}: case_id '{case.get('case_id')}' does not match manifest"
            )
        _validate_case(case, case_path, require_reviewed, errors)

        if check_assets:
            paper = case.get("paper", {})
            pdf = paper.get("pdf")
            if isinstance(pdf, dict):
                _validate_asset(pdf, f"{case_path}: paper.pdf", repository_root, errors)
            tex = paper.get("tex")
            if isinstance(tex, dict):
                archive = tex.get("archive")
                if isinstance(archive, dict):
                    _validate_asset(
                        archive,
                        f"{case_path}: paper.tex.archive",
                        repository_root,
                        errors,
                    )
                for file_index, source_file in enumerate(tex.get("files", [])):
                    if isinstance(source_file, dict):
                        _validate_asset(
                            source_file,
                            f"{case_path}: paper.tex.files[{file_index}]",
                            repository_root,
                            errors,
                        )
            _validate_evidence_anchors(case, case_path, repository_root, errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--check-assets", action="store_true")
    parser.add_argument("--require-reviewed", action="store_true")
    args = parser.parse_args()

    errors = validate_corpus(
        args.manifest,
        check_assets=args.check_assets,
        require_reviewed=args.require_reviewed,
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"Validated corpus: {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
