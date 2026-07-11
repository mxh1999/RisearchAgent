# Read-Paper Evaluation

This directory contains the evidence-centered evaluation contract for the V2
`read-paper` skill. The checked-in YAML files contain tasks, candidate references,
and the rubric. PDFs and TeX archives remain under the gitignored `data/` tree and
are identified by immutable SHA256 values and acquisition URLs.

## Pilot status

`pilot_v0` contains two candidate cases:

- VLFM exercises PDF-first reading, zero-shot terminology, compact two-column
  result tables, and author-stated limitations.
- PaLM-E exercises a long multimodal paper, dense multi-level table headers,
  appendix evidence, and raw TeX table verification.

Both cases intentionally have `review.status: draft`. They become gold references
only after a human checks every critical claim, selected numeric record, header
path, evidence locator, limitation, and known ambiguity. Validation with
`--require-reviewed` fails while either case remains draft.

## Validation

Run structural validation from the repository root:

```bash
conda run -n paper_reader python -m evals.read_paper.validation \
  evals/read_paper/pilot_v0/manifest.yaml
```

Also hash the local PDF and TeX assets:

```bash
conda run -n paper_reader python -m evals.read_paper.validation \
  evals/read_paper/pilot_v0/manifest.yaml --check-assets
```

Require completed human review before an acceptance run:

```bash
conda run -n paper_reader python -m evals.read_paper.validation \
  evals/read_paper/pilot_v0/manifest.yaml --check-assets --require-reviewed
```

## Review procedure

For each case, a human reviewer must:

1. Confirm the ArXiv version, PDF page count, and SHA256.
2. Open every referenced PDF page and visually verify each critical item.
3. Check every selected table value against its full row and column header path.
4. For TeX evidence, check the frozen raw source file rather than parser output.
5. Confirm that limitations distinguish author statements from reviewer inference.
6. Confirm that each known ambiguity describes the disclosure expected from a run.
7. Record `human_reviewer` and `reviewed_at`, then change status to `reviewed`.

The pilot should be reviewed before selecting the remaining six papers. Changes
to field semantics after review require a new schema or corpus version rather than
silently rewriting a frozen benchmark.
