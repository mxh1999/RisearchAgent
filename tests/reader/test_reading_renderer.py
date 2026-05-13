from __future__ import annotations

import json

from src.reader.reading_renderer import (
    render_reading_markdown,
    write_reading_package,
)
from src.reader.staged_models import (
    Evidence,
    ExperimentRecord,
    MethodModule,
    PaperReadingPackage,
    PageText,
    PaperSummary,
    TopicRelation,
)


def _reading_package() -> PaperReadingPackage:
    return PaperReadingPackage(
        paper_id="sample_paper",
        title="Sample Paper",
        source_path="papers/sample.pdf",
        pages=[PageText(page=1, text="Abstract text", char_start=0, char_end=13)],
        summary=PaperSummary(
            problem="The paper studies navigation decisions.",
            method="It scores candidate viewpoints.",
            takeaway="The key idea is learned utility over memory.",
            contributions=["Task-conditioned utility scoring"],
        ),
        claims=[
            Evidence(
                text="The method improves SPL.",
                page=7,
                section="Experiments",
                quote="Our method improves SPL by 5 points.",
                confidence="high",
            )
        ],
        method_modules=[
            MethodModule(
                name="Utility Head",
                role="Scores object and frontier candidates.",
                inputs=["3D memory", "goal embedding"],
                outputs=["candidate utility"],
            )
        ],
        experiments=[
            ExperimentRecord(
                benchmark="GOAT-Bench",
                setting="val unseen",
                metric="SPL",
                method="SampleNav",
                value=35.1,
                higher_is_better=True,
                source=Evidence(
                    text="SPL result",
                    page=8,
                    section="Experiments",
                    quote="SampleNav obtains 35.1 SPL.",
                    confidence="high",
                ),
            )
        ],
        topic_relation=TopicRelation(
            relevance="core",
            concept_axes=["task_conditioned_utility"],
            collision_risk="medium",
            differentiation="Uses explicit utility rather than prompted reasoning.",
        ),
        critique=["Needs stronger baseline comparisons."],
        follow_up_questions=["How is utility supervised?"],
    )


def test_render_reading_markdown_contains_core_sections() -> None:
    package = _reading_package()

    markdown = render_reading_markdown(package)

    assert "# Sample Paper" in markdown
    assert "One-Sentence Takeaway" in markdown
    assert "The key idea is learned utility over memory." in markdown
    assert "Claims And Evidence" in markdown
    assert "The method improves SPL." in markdown
    assert "Critical Assessment" in markdown


def test_write_reading_package_writes_json_and_markdown(tmp_path) -> None:
    package = _reading_package()

    json_path, markdown_path = write_reading_package(package, tmp_path)

    assert json_path.name == "sample_paper.json"
    assert markdown_path.name == "sample_paper.reading.md"
    assert json.loads(json_path.read_text(encoding="utf-8"))["paper_id"] == "sample_paper"
    assert "# Sample Paper" in markdown_path.read_text(encoding="utf-8")
