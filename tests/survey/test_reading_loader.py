from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.reader.staged_models import PaperReadingPackage, PaperSummary
from src.survey.reading_loader import load_reading_packages


def _package(paper_id: str, title: str) -> PaperReadingPackage:
    return PaperReadingPackage(
        paper_id=paper_id,
        title=title,
        source_path=f"papers/{paper_id}.pdf",
        summary=PaperSummary(
            problem="Navigation needs better decision models.",
            method="The paper scores candidate actions.",
            takeaway=f"{title} is relevant to utility-based navigation.",
            contributions=["Candidate scoring"],
        ),
    )


def _write_package(directory: Path, package: PaperReadingPackage) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{package.paper_id}.json").write_text(
        json.dumps(package.to_dict()), encoding="utf-8"
    )


def test_load_reading_packages_sorted_by_paper_id(tmp_path: Path) -> None:
    _write_package(tmp_path, _package("vlfm", "VLFM"))
    _write_package(tmp_path, _package("mtu3d", "MTU3D"))

    packages = load_reading_packages(tmp_path)

    assert [package.paper_id for package in packages] == ["mtu3d", "vlfm"]


def test_load_reading_packages_rejects_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Readings directory not found"):
        load_reading_packages(tmp_path / "missing")


def test_load_reading_packages_rejects_empty_directory(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)

    with pytest.raises(ValueError, match="No reading package JSON files found"):
        load_reading_packages(tmp_path)


def test_load_reading_packages_rejects_duplicate_paper_ids(tmp_path: Path) -> None:
    _write_package(tmp_path, _package("mtu3d", "MTU3D"))
    (tmp_path / "copy.json").write_text(
        json.dumps(_package("mtu3d", "MTU3D Copy").to_dict()), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Duplicate paper_id: mtu3d"):
        load_reading_packages(tmp_path)


def test_load_reading_packages_rejects_malformed_json(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid reading package JSON"):
        load_reading_packages(tmp_path)


def test_load_reading_packages_rejects_malformed_package(tmp_path: Path) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "bad.json").write_text(
        json.dumps({"paper_id": "bad"}), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Malformed reading package"):
        load_reading_packages(tmp_path)
