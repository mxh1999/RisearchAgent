from __future__ import annotations

import json
from pathlib import Path

from src.reader.staged_models import PaperReadingPackage


def load_reading_packages(readings_dir: Path) -> list[PaperReadingPackage]:
    if not readings_dir.exists() or not readings_dir.is_dir():
        raise FileNotFoundError(f"Readings directory not found: {readings_dir}")

    json_paths = sorted(readings_dir.glob("*.json"))
    if not json_paths:
        raise ValueError(f"No reading package JSON files found in {readings_dir}")

    packages: list[PaperReadingPackage] = []
    seen_ids: set[str] = set()
    for path in json_paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid reading package JSON {path}: {exc}") from exc

        if not isinstance(raw, dict):
            raise ValueError(f"Malformed reading package {path}: expected JSON object")

        try:
            package = PaperReadingPackage.from_dict(raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Malformed reading package {path}: {exc}") from exc

        if package.paper_id in seen_ids:
            raise ValueError(f"Duplicate paper_id: {package.paper_id}")
        seen_ids.add(package.paper_id)
        packages.append(package)

    return sorted(packages, key=lambda package: package.paper_id)
