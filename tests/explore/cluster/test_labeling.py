"""Deterministic tests for cluster labeling validation logic.

LLM-call tests (T1) live separately under @pytest.mark.llm.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.explore.cluster.algorithm import RawCluster
from src.explore.cluster.labeling import (
    SLUG_PATTERN,
    fallback_labels,
    jaccard,
    normalize_slug,
    validate_inheritance,
)
from src.explore.state import Cluster, ClusterSnapshot


# —————————————————————————————————————————————————————————————
# normalize_slug
# —————————————————————————————————————————————————————————————


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("zero-shot-objnav", "zero-shot-objnav"),
        ("Zero-Shot-ObjNav", "zero-shot-objnav"),
        ("zero_shot_objnav", "zero-shot-objnav"),
        ("zero shot objnav", "zero-shot-objnav"),
        ("zero--shot--objnav", "zero-shot-objnav"),
        ("vln", "vln"),
        ("zero-shot-object-goal-navigation", "zero-shot-object"),  # capped to 3 tokens
    ],
)
def test_normalize_slug_canonicalizes(raw, expected):
    assert normalize_slug(raw) == expected


@pytest.mark.parametrize("raw", ["", " ", None, "$$$", "---"])
def test_normalize_slug_returns_none_for_unsalvageable(raw):
    assert normalize_slug(raw) is None


def test_normalize_slug_output_always_matches_pattern():
    samples = ["Zero-Shot Nav", "vln_ce_v2", "RLHF based", "  spaced  "]
    for s in samples:
        result = normalize_slug(s)
        if result is not None:
            assert SLUG_PATTERN.match(result), f"Bad slug: {result!r}"


# —————————————————————————————————————————————————————————————
# jaccard
# —————————————————————————————————————————————————————————————


def test_jaccard_full_overlap():
    assert jaccard({1, 2, 3}, {1, 2, 3}) == 1.0


def test_jaccard_no_overlap():
    assert jaccard({1, 2}, {3, 4}) == 0.0


def test_jaccard_partial():
    # |{1,2}| / |{1,2,3,4}| = 0.5
    assert jaccard({1, 2, 3}, {1, 2, 4}) == 0.5


def test_jaccard_both_empty():
    assert jaccard(set(), set()) == 0.0


# —————————————————————————————————————————————————————————————
# validate_inheritance
# —————————————————————————————————————————————————————————————


def _prev_snapshot_with(slug: str, paper_ids: list[str]) -> ClusterSnapshot:
    return ClusterSnapshot(
        snapshot_id="prev",
        generated_at=datetime.now(),
        generated_after_turn=1,
        n_papers_at_time=len(paper_ids),
        clusters=[
            Cluster(
                slug=slug,
                display_label=slug,
                description="test",
                paper_ids=paper_ids,
                size=len(paper_ids),
                centroid_paper_id=paper_ids[0] if paper_ids else None,
                representative_paper_ids=paper_ids[:3],
                year_range=(2024, 2024),
                density="dense",
                first_seen_in_snapshot="prev",
            )
        ],
    )


def test_validate_inheritance_keeps_high_overlap():
    prev = _prev_snapshot_with("vln-ce", ["a", "b", "c", "d", "e"])
    # 4/5 overlap
    new_ids = ["a", "b", "c", "d", "z"]
    result = validate_inheritance(new_ids, "vln-ce", prev)
    assert result == "vln-ce"


def test_validate_inheritance_drops_low_overlap():
    prev = _prev_snapshot_with("vln-ce", ["a", "b", "c", "d", "e"])
    # 1/9 overlap = 0.11 < 0.3
    new_ids = ["a", "x", "y", "z", "w"]
    result = validate_inheritance(new_ids, "vln-ce", prev)
    assert result is None


def test_validate_inheritance_drops_unknown_slug():
    prev = _prev_snapshot_with("vln-ce", ["a", "b"])
    result = validate_inheritance(["a", "b"], "ghost-slug", prev)
    assert result is None


def test_validate_inheritance_returns_none_on_no_prev():
    assert validate_inheritance(["a"], "vln-ce", None) is None


def test_validate_inheritance_returns_none_when_no_claim():
    prev = _prev_snapshot_with("vln-ce", ["a", "b"])
    assert validate_inheritance(["a", "b"], None, prev) is None


# —————————————————————————————————————————————————————————————
# fallback_labels
# —————————————————————————————————————————————————————————————


def _raw(temp_id: int, n: int) -> RawCluster:
    return RawCluster(
        temp_id=temp_id,
        paper_ids=[f"p{temp_id}-{i}" for i in range(n)],
        centroid_paper_id=f"p{temp_id}-0",
        representative_paper_ids=[f"p{temp_id}-0"],
        shared_benchmarks=[],
        top_authors=[],
        year_range=(2024, 2024),
        density="dense",
        mean_probability=0.9,
    )


def test_fallback_labels_match_input_count():
    raws = [_raw(0, 5), _raw(1, 4), _raw(2, 3)]
    out = fallback_labels(raws)
    assert len(out) == 3
    assert [l.slug for l in out] == ["cluster-0", "cluster-1", "cluster-2"]
    assert all(l.inherited_from_slug is None for l in out)
