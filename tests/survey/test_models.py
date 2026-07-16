from src.survey.models import (
    ConceptAxis,
    TopicProfile,
    TopicQuery,
    TopicScope,
    make_topic_id,
)


def test_make_topic_id_normalizes_research_title() -> None:
    topic_id = make_topic_id("Task-conditioned 3D Utility Learning for Navigation!")
    assert topic_id == "task_conditioned_3d_utility_learning_for_navigation"


def test_topic_profile_round_trip_dict() -> None:
    profile = TopicProfile(
        topic_id="decision_aware_3d_nav",
        name="Decision-Aware 3D Navigation",
        description="Study how 3D memory becomes navigation decisions.",
        intent="Find papers about task-conditioned utility over 3D memories.",
        concept_axes=[
            ConceptAxis(
                name="task_conditioned_utility",
                description="Scores objects, frontiers, regions, or viewpoints.",
            )
        ],
        scope=TopicScope(
            positive=["3D memory for embodied navigation"],
            negative=["pure SLAM without semantic decisions"],
            adjacent=["static 3D grounding"],
            collision=["MSGNav"],
        ),
        anchor_papers=["MTU3D"],
        benchmark_hints=["GOAT-Bench"],
        search_queries=[
            TopicQuery(
                name="direct",
                query='"embodied navigation" "3D memory"',
                purpose="Find direct matches.",
            )
        ],
        open_questions=["What utility supervision is available?"],
    )

    restored = TopicProfile.from_dict(profile.to_dict())

    assert restored == profile
    assert restored.search_queries[0].query == '"embodied navigation" "3D memory"'
