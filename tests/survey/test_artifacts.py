import json

import yaml

from src.survey.artifacts import TopicArtifactManager
from src.survey.models import ConceptAxis, SurveyEvent, TopicProfile, TopicScope


def make_profile() -> TopicProfile:
    return TopicProfile(
        topic_id="decision_aware_3d_nav",
        name="Decision-Aware 3D Navigation",
        description="Study how 3D memory becomes navigation decisions.",
        intent="Find papers about task-conditioned utility over 3D memories.",
        concept_axes=[
            ConceptAxis(
                name="task_conditioned_utility",
                description="Scores object, frontier, region, or viewpoint candidates.",
            )
        ],
        scope=TopicScope(
            positive=["3D memory for embodied navigation"],
            negative=["pure SLAM without semantic decisions"],
        ),
    )


def test_create_topic_artifacts_writes_stable_files(tmp_path) -> None:
    manager = TopicArtifactManager(tmp_path)
    paths = manager.create_or_update_topic(make_profile())

    assert paths.topic_dir == tmp_path / "decision_aware_3d_nav"
    assert paths.topic_yaml.exists()
    assert (paths.topic_dir / "survey.md").exists()
    assert (paths.topic_dir / "papers.md").exists()
    assert (paths.topic_dir / "references.md").exists()
    assert (paths.topic_dir / "positioning.md").exists()
    assert (paths.topic_dir / "state" / "survey_events.jsonl").exists()

    raw = yaml.safe_load(paths.topic_yaml.read_text(encoding="utf-8"))
    assert raw["topic_id"] == "decision_aware_3d_nav"
    assert raw["concept_axes"][0]["name"] == "task_conditioned_utility"


def test_update_auto_block_preserves_manual_text(tmp_path) -> None:
    manager = TopicArtifactManager(tmp_path)
    paths = manager.create_or_update_topic(make_profile())
    survey_path = paths.topic_dir / "survey.md"
    survey_path.write_text(
        "# Survey\n\nManual note.\n\n"
        "<!-- BEGIN AUTO:taxonomy -->\nOld taxonomy\n<!-- END AUTO:taxonomy -->\n",
        encoding="utf-8",
    )

    manager.update_auto_block(
        survey_path,
        "taxonomy",
        "## Taxonomy\n\n- Task-conditioned utility\n",
    )

    content = survey_path.read_text(encoding="utf-8")
    assert "Manual note." in content
    assert "Old taxonomy" not in content
    assert "- Task-conditioned utility" in content


def test_append_event_writes_jsonl(tmp_path) -> None:
    manager = TopicArtifactManager(tmp_path)
    paths = manager.create_or_update_topic(make_profile())

    manager.append_event(
        paths.topic_dir,
        SurveyEvent(event_type="refine", message="Created topic profile."),
    )

    lines = (paths.topic_dir / "state" / "survey_events.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event_type"] == "refine"
