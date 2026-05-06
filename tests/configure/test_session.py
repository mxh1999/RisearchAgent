"""Deterministic tests for ConfigureSession."""

from __future__ import annotations

import pytest

from src.configure.session import (
    DEFAULT_ANCHOR_COUNT_PER_CLUSTER,
    DEFAULT_RELEVANCE_THRESHOLD,
    ConfigureSession,
)


def test_from_field_map_selects_all_subareas_by_default(fm):
    s = ConfigureSession.from_field_map(fm)
    assert s.selected_slugs == {sa.slug for sa in fm.sub_areas}
    assert s.relevance_threshold == DEFAULT_RELEVANCE_THRESHOLD
    assert all(
        s.anchor_count[sa.slug] == DEFAULT_ANCHOR_COUNT_PER_CLUSTER
        for sa in fm.sub_areas
    )
    assert s.dirty is False


def test_select_replaces_set(fm):
    s = ConfigureSession.from_field_map(fm)
    all_slugs = [sa.slug for sa in fm.sub_areas]
    s.select(["vln-ce"], all_slugs)
    assert s.selected_slugs == {"vln-ce"}
    assert s.dirty is True


def test_select_unknown_slug_raises(fm):
    s = ConfigureSession.from_field_map(fm)
    with pytest.raises(ValueError, match="Unknown slugs"):
        s.select(["does-not-exist"], [sa.slug for sa in fm.sub_areas])


def test_select_all_and_none(fm):
    all_slugs = [sa.slug for sa in fm.sub_areas]
    s = ConfigureSession.from_field_map(fm)
    s.select_none()
    assert s.selected_slugs == set()
    s.select_all(all_slugs)
    assert s.selected_slugs == set(all_slugs)


def test_drop_idempotent_for_already_unselected(fm):
    s = ConfigureSession.from_field_map(fm)
    s.drop("vln-ce")
    assert "vln-ce" not in s.selected_slugs
    s.drop("vln-ce")  # second drop is a no-op, no error
    assert s.dirty is True


def test_rename_overrides_label(fm):
    s = ConfigureSession.from_field_map(fm)
    all_slugs = [sa.slug for sa in fm.sub_areas]
    s.rename("vln-ce", "VLN-CE (focused)", all_slugs)
    assert s.label_for("vln-ce", "default") == "VLN-CE (focused)"
    assert s.label_for("other", "default") == "default"


@pytest.mark.parametrize("bad_label", ["", "   "])
def test_rename_rejects_empty_label(fm, bad_label):
    s = ConfigureSession.from_field_map(fm)
    all_slugs = [sa.slug for sa in fm.sub_areas]
    with pytest.raises(ValueError, match="empty"):
        s.rename("vln-ce", bad_label, all_slugs)


def test_set_threshold_in_range(fm):
    s = ConfigureSession.from_field_map(fm)
    s.set_threshold(8)
    assert s.relevance_threshold == 8


@pytest.mark.parametrize("n", [-1, 11, 100])
def test_set_threshold_out_of_range_raises(fm, n):
    s = ConfigureSession.from_field_map(fm)
    with pytest.raises(ValueError):
        s.set_threshold(n)


def test_set_anchor_count_negative_raises(fm):
    s = ConfigureSession.from_field_map(fm)
    all_slugs = [sa.slug for sa in fm.sub_areas]
    with pytest.raises(ValueError):
        s.set_anchor_count("vln-ce", -1, all_slugs)


def test_mark_committed_clears_dirty(fm):
    s = ConfigureSession.from_field_map(fm)
    s.set_threshold(7)
    assert s.dirty
    s.mark_committed()
    assert not s.dirty
