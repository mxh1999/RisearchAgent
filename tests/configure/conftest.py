"""Shared fixtures for tests/configure/."""

from __future__ import annotations

import pytest

from src.synthesize.types import FieldMap
from tests.synthesize.conftest import make_minimal_field_map


@pytest.fixture
def fm() -> FieldMap:
    return make_minimal_field_map()
