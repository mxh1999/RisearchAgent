from pathlib import Path

from evals.read_paper.validation import validate_corpus


MANIFEST = Path("evals/read_paper/pilot_v0/manifest.yaml")


def test_pilot_corpus_is_structurally_valid() -> None:
    assert validate_corpus(MANIFEST) == []


def test_draft_pilot_cannot_be_used_as_reviewed_gold() -> None:
    errors = validate_corpus(MANIFEST, require_reviewed=True)

    assert len(errors) == 2
    assert all("expected 'reviewed'" in error for error in errors)
