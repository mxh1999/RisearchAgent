from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional, Tuple

import pytest

from src.reader.page_extractor import extract_pages_from_text_file
from src.reader.reading_renderer import write_reading_package
from src.reader.staged_reader import StagedPaperReader


class FakeLLM:
    def __init__(self) -> None:
        self.calls: List[Tuple[str, Optional[str], Optional[float]]] = []

    async def generate_json(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        stage = self._stage_from_prompt(prompt)
        self.calls.append((stage, model, temperature))
        if stage == "summary":
            return {
                "summary": {
                    "problem": "Navigation methods need better 3D decisions.",
                    "method": "The paper scores candidates from memory.",
                    "takeaway": "Utility scoring is the central mechanism.",
                    "contributions": ["A staged utility model"],
                }
            }
        if stage == "section_notes":
            return {"claims": [], "critique": [], "follow_up_questions": []}
        if stage == "method":
            return {"method_modules": []}
        if stage == "experiments":
            return {"experiments": []}
        if stage == "topic_relation":
            return {
                "topic_relation": {
                    "relevance": "core",
                    "concept_axes": [],
                    "collision_risk": "low",
                    "differentiation": "Synthetic test relation.",
                }
            }
        raise AssertionError(f"Unexpected stage: {stage}")

    def _stage_from_prompt(self, prompt: str) -> str:
        lines = prompt.splitlines()
        for index, line in enumerate(lines[:-1]):
            if line == "## Stage":
                return lines[index + 1].strip()
        raise AssertionError("Prompt is missing a controlled stage section")


@pytest.mark.asyncio
async def test_text_file_to_reading_artifacts(tmp_path: Path) -> None:
    text_path = tmp_path / "paper.txt"
    text_path.write_text(
        "Abstract\nThis paper studies navigation.\n\nExperiments\nNo table.",
        encoding="utf-8",
    )
    pages = extract_pages_from_text_file(text_path)
    llm = FakeLLM()
    reader = StagedPaperReader(llm, model="gemini-2.5-pro")

    package = await reader.read(
        paper_id="sample",
        title="Sample Paper",
        source_path=str(text_path),
        pages=pages,
        topic=None,
    )
    json_path, markdown_path = write_reading_package(package, tmp_path / "out")

    assert json_path.exists()
    assert markdown_path.exists()
    assert json.loads(json_path.read_text(encoding="utf-8"))["paper_id"] == "sample"
    assert "Utility scoring is the central mechanism." in markdown_path.read_text(
        encoding="utf-8"
    )
    assert llm.calls == [
        ("summary", "gemini-2.5-pro", 0.1),
        ("section_notes", "gemini-2.5-pro", 0.1),
        ("method", "gemini-2.5-pro", 0.1),
        ("experiments", "gemini-2.5-pro", 0.1),
        ("topic_relation", "gemini-2.5-pro", 0.1),
    ]
