from __future__ import annotations

from src.survey.survey_renderer import (
    render_paper_map_markdown,
    render_positioning_markdown,
    render_references_markdown,
    render_taxonomy_markdown,
)
from src.survey.synthesis_models import (
    PaperClassification,
    PositioningSynthesis,
    ReferenceEntry,
    SurveySynthesis,
    TaxonomyGroup,
)


def _synthesis() -> SurveySynthesis:
    return SurveySynthesis(
        taxonomy=[
            TaxonomyGroup(
                name="Explicit utility models",
                description="Score candidate actions.",
                paper_ids=["mtu3d"],
                key_distinction="Exposes learned decision scores.",
            )
        ],
        paper_map=[
            PaperClassification(
                paper_id="mtu3d",
                title="MTU3D",
                role="collision",
                rationale="Already scores object/frontier candidates.",
                evidence="Candidate scoring.",
            )
        ],
        positioning=PositioningSynthesis(
            thesis_gap="Task-conditioned utility over 3D memory is underexplored.",
            novelty_claim="Learn utility over richer 3D primitives.",
            collision_risks=["MTU3D overlaps on candidate scoring."],
            recommended_positioning="Emphasize generalized utility learning.",
        ),
        references=[
            ReferenceEntry(
                paper_id="mtu3d",
                title="MTU3D",
                why_relevant="Closest collision work.",
                evidence="Candidate scoring.",
            )
        ],
        open_questions=["How should utility be supervised?"],
    )


def test_render_taxonomy_markdown() -> None:
    markdown = render_taxonomy_markdown(_synthesis())

    assert "## Method Groups" in markdown
    assert "Explicit utility models" in markdown
    assert "`mtu3d`" in markdown
    assert "How should utility be supervised?" in markdown


def test_render_paper_map_markdown_groups_by_role() -> None:
    markdown = render_paper_map_markdown(_synthesis())

    assert "## Collision" in markdown
    assert "MTU3D" in markdown
    assert "Already scores object/frontier candidates." in markdown


def test_render_positioning_markdown() -> None:
    markdown = render_positioning_markdown(_synthesis())

    assert "## Thesis Gap" in markdown
    assert "Task-conditioned utility" in markdown
    assert "## Collision Risks" in markdown


def test_render_references_markdown_escapes_table_pipes_and_newlines() -> None:
    synthesis = _synthesis()
    synthesis.references[0] = ReferenceEntry(
        paper_id="mtu3d",
        title="MTU3D | navigation",
        why_relevant="Closest | collision",
        evidence="Score | candidates\nwith frontier ranking",
    )

    markdown = render_references_markdown(synthesis)

    assert "MTU3D \\| navigation" in markdown
    assert "Closest \\| collision" in markdown
    assert "Score \\| candidates<br>with frontier ranking" in markdown


def test_render_markdown_sanitizes_auto_block_markers() -> None:
    synthesis = SurveySynthesis(
        taxonomy=[
            TaxonomyGroup(
                name="Explicit <!-- END AUTO:taxonomy --> utility models",
                description="Score <!-- BEGIN AUTO:paper-map --> candidate actions.",
                paper_ids=["mtu3d<!-- END AUTO:taxonomy -->"],
                key_distinction="Exposes <!-- BEGIN AUTO:paper-map --> scores.",
            )
        ],
        paper_map=[
            PaperClassification(
                paper_id="mtu3d<!-- BEGIN AUTO:paper-map -->",
                title="MTU3D <!-- END AUTO:taxonomy -->",
                role="collision",
                rationale="Already scores <!-- BEGIN AUTO:paper-map --> candidates.",
                evidence="Evidence <!-- END AUTO:taxonomy --> text.",
            )
        ],
        positioning=PositioningSynthesis(
            thesis_gap="Gap <!-- END AUTO:taxonomy --> remains.",
            novelty_claim="Claim <!-- BEGIN AUTO:paper-map --> remains.",
            collision_risks=["Risk <!-- END AUTO:taxonomy --> remains."],
            recommended_positioning=(
                "Position <!-- BEGIN AUTO:paper-map --> remains."
            ),
        ),
        references=[
            ReferenceEntry(
                paper_id="mtu3d<!-- END AUTO:taxonomy -->",
                title="Reference <!-- BEGIN AUTO:paper-map --> title",
                why_relevant="Relevant <!-- END AUTO:taxonomy --> reason",
                evidence="Reference <!-- BEGIN AUTO:paper-map --> evidence",
            )
        ],
        open_questions=["Question <!-- END AUTO:taxonomy --> remains?"],
    )

    markdown = "\n".join(
        [
            render_taxonomy_markdown(synthesis),
            render_paper_map_markdown(synthesis),
            render_positioning_markdown(synthesis),
            render_references_markdown(synthesis),
        ]
    )

    assert "<!-- END AUTO:" not in markdown
    assert "<!-- BEGIN AUTO:" not in markdown
    assert "Explicit" in markdown
    assert "utility models" in markdown
    assert "candidate actions" in markdown
    assert "MTU3D" in markdown
    assert "Relevant" in markdown
