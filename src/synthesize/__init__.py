"""Synthesize stage: ExplorationState → FieldMap → Markdown.

See docs/onboard-redesign/10-synthesize.md.

Public API:
  synthesize(state, llm, *, model=None) -> FieldMap   # Stage 1 (LLM)
  render_field_map(fm) -> str                         # Stage 2 (deterministic)
  diff_field_maps(old, new) -> FieldMapDiff           # Refine flow
  render_diff_markdown(diff) -> str
"""

from src.synthesize.diff import (
    FieldMapDiff,
    SubAreaChange,
    diff_field_maps,
    render_diff_markdown,
)
from src.synthesize.render import render_field_map
from src.synthesize.synthesizer import (
    SynthesisError,
    derive_header_from_state,
    synthesize,
    validate_citations,
)
from src.synthesize.types import (
    ActiveGroup,
    AnchorPaper,
    BenchmarkEntry,
    ClassicPaper,
    FieldMap,
    Header,
    OpenQuestion,
    PaperRef,
    SchoolOfThought,
    SubArea,
)

__all__ = [
    # types
    "FieldMap",
    "Header",
    "PaperRef",
    "SubArea",
    "BenchmarkEntry",
    "SchoolOfThought",
    "ClassicPaper",
    "ActiveGroup",
    "OpenQuestion",
    "AnchorPaper",
    # API
    "synthesize",
    "validate_citations",
    "derive_header_from_state",
    "SynthesisError",
    "render_field_map",
    "diff_field_maps",
    "render_diff_markdown",
    "FieldMapDiff",
    "SubAreaChange",
]
