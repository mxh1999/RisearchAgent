import json

import pytest
import yaml

from src.survey.artifacts import AUTO_BEGIN, AUTO_END
from src.survey.artifacts import TopicArtifactManager
from src.survey.models import ConceptAxis, SurveyEvent, TopicProfile, TopicScope


def make_profile(topic_id: str = "decision_aware_3d_nav") -> TopicProfile:
    return TopicProfile(
        topic_id=topic_id,
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
    begin = AUTO_BEGIN.format(name="taxonomy")
    end = AUTO_END.format(name="taxonomy")
    survey_path.write_text(
        "# Survey\n\nManual note.\n\n"
        f"{begin}\nOld taxonomy\n{end}\n\nManual conclusion.\n",
        encoding="utf-8",
    )

    manager.update_auto_block(
        survey_path,
        "taxonomy",
        "## Taxonomy\n\n- Task-conditioned utility\n",
    )

    content = survey_path.read_text(encoding="utf-8")
    assert "Manual note." in content
    assert "Manual conclusion." in content
    assert "Old taxonomy" not in content
    assert "- Task-conditioned utility" in content
    assert content.count(begin) == 1
    assert content.count(end) == 1
    assert content.index("Manual note.") < content.index(begin)
    assert content.index(end) < content.index("Manual conclusion.")


def test_update_auto_block_uses_end_marker_after_target_begin(tmp_path) -> None:
    manager = TopicArtifactManager(tmp_path)
    path = tmp_path / "survey.md"
    begin = AUTO_BEGIN.format(name="taxonomy")
    end = AUTO_END.format(name="taxonomy")
    path.write_text(
        "# Survey\n\nManual preface.\n"
        f"{end}\n"
        "Manual text between stray end marker and real block.\n\n"
        f"{begin}\nOld taxonomy\n{end}\n\n"
        "Manual appendix.\n",
        encoding="utf-8",
    )

    manager.update_auto_block(path, "taxonomy", "New taxonomy")

    content = path.read_text(encoding="utf-8")
    assert "Manual preface." in content
    assert "Manual text between stray end marker and real block." in content
    assert "Manual appendix." in content
    assert "Old taxonomy" not in content
    assert "New taxonomy" in content
    assert content.count(begin) == 1
    assert content.count(end) == 2
    assert content.index(begin) > content.index("Manual text between stray end marker")


def test_update_auto_block_appends_when_target_end_missing(tmp_path) -> None:
    manager = TopicArtifactManager(tmp_path)
    path = tmp_path / "survey.md"
    begin = AUTO_BEGIN.format(name="taxonomy")
    end = AUTO_END.format(name="taxonomy")
    path.write_text(
        "# Survey\n\nManual note before incomplete block.\n\n"
        f"{begin}\nOld taxonomy without end marker.\n"
        "Manual note after incomplete block.\n",
        encoding="utf-8",
    )

    manager.update_auto_block(path, "taxonomy", "New taxonomy")

    content = path.read_text(encoding="utf-8")
    assert "Manual note before incomplete block." in content
    assert "Old taxonomy without end marker." in content
    assert "Manual note after incomplete block." in content
    assert "New taxonomy" in content
    assert content.count(begin) == 2
    assert content.count(end) == 1


def test_update_auto_block_creates_parent_dirs_for_new_path(tmp_path) -> None:
    manager = TopicArtifactManager(tmp_path)
    path = tmp_path / "nested" / "survey.md"

    manager.update_auto_block(path, "taxonomy", "New taxonomy")

    content = path.read_text(encoding="utf-8")
    assert "New taxonomy" in content
    assert content.count(AUTO_BEGIN.format(name="taxonomy")) == 1
    assert content.count(AUTO_END.format(name="taxonomy")) == 1


@pytest.mark.parametrize(
    "topic_id",
    [
        "",
        ".",
        "..",
        "../escape",
        "nested/topic",
        "nested\\topic",
        "/absolute",
        "C:/absolute",
    ],
)
def test_create_topic_rejects_unsafe_topic_id(tmp_path, topic_id: str) -> None:
    manager = TopicArtifactManager(tmp_path)

    with pytest.raises(ValueError):
        manager.create_or_update_topic(make_profile(topic_id))


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
