"""Citation provider abstraction.

Public:
    CitationProvider — abstract base
    NullProvider     — returns empty (for citation_provider: none)
    SemanticScholarProvider — real impl backed by api.semanticscholar.org
    PaperCitationInfo, RelatedPaper — return types

See docs/onboard-redesign/11-citation-provider.md.
"""

from src.explore.citations.provider import (
    CitationProvider,
    NullProvider,
    PaperCitationInfo,
    RelatedPaper,
)
from src.explore.citations.rate_limiter import AsyncRateLimiter
from src.explore.citations.semantic_scholar import (
    DEGRADE_AFTER_CONSECUTIVE_ERRORS,
    SemanticScholarProvider,
    make_provider_from_env,
    normalize_arxiv_id,
)

__all__ = [
    "CitationProvider",
    "NullProvider",
    "PaperCitationInfo",
    "RelatedPaper",
    "AsyncRateLimiter",
    "SemanticScholarProvider",
    "make_provider_from_env",
    "normalize_arxiv_id",
    "DEGRADE_AFTER_CONSECUTIVE_ERRORS",
]
