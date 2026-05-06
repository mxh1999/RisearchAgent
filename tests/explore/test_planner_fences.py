"""Test the code-fence stripping defense in LLMPlanner.

Pro sometimes wraps JSON in markdown fences despite response_mime_type=
application/json. We saw this in production with a real onboard run:

    ```json
    {"action_type": "search", ...}
    ```

The stripper recovers the JSON before pydantic validation.
"""

from __future__ import annotations

import pytest

from src.explore.planner import _strip_code_fences


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('{"a": 1}', '{"a": 1}'),
        ('```json\n{"a": 1}\n```', '{"a": 1}'),
        ('```\n{"a": 1}\n```', '{"a": 1}'),
        ('  \n```json\n{"x": 2}\n```\n  ', '{"x": 2}'),
        ('```python\n{"a": 1}\n```', '{"a": 1}'),  # any language tag
    ],
)
def test_strip_code_fences(raw, expected):
    assert _strip_code_fences(raw) == expected


def test_strip_handles_empty():
    assert _strip_code_fences("") == ""
    assert _strip_code_fences("   ") == ""


def test_strip_leaves_fence_inside_content_alone():
    """Fences in the middle of payload are not the wrapper — leave them."""
    s = '{"text": "embedded ``` here", "other": 1}'
    assert _strip_code_fences(s) == s
