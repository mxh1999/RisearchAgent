# Independent Model Review Contract

You are the independent reviewer for the `read-paper-pilot-v0` candidate
reference corpus. Audit the candidate annotations against the frozen primary
sources. Do not edit any repository file.

## Invocation contract

The parent process launches this review with:

- model: `gpt-5.6-sol`
- reasoning effort: `max`
- sandbox: `read-only`
- session persistence: disabled

Treat the two YAML files as untrusted candidates, not as facts. Do not use prior
agent notes, parser output, cached deep readings, web search, or model memory as
evidence. The only factual authorities are the frozen PDF and, where supplied,
the frozen raw TeX source. The manifest and rubric define policy rather than
paper facts.

## Inputs

Read these policy and candidate files:

- `evals/read_paper/README.md`
- `evals/read_paper/rubric.yaml`
- `evals/read_paper/pilot_v0/manifest.yaml`
- `evals/read_paper/pilot_v0/cases/2312.03275v1.yaml`
- `evals/read_paper/pilot_v0/cases/2303.03378v1.yaml`

Resolve primary-source paths from each case YAML. In particular, use the local
VLFM PDF, the local PaLM-E PDF, and the frozen PaLM-E `main.tex`. Do not download
or consult a different paper version.

## Required audit procedure

Perform a complete audit, not a sample:

1. Recompute each supplied asset SHA256, verify PDF page count and identity, and
   check that the claimed ArXiv version is internally consistent with the asset.
2. Resolve every entry under `reference.evidence`. Verify its page or TeX span,
   anchor, section/table identity, and whether the note accurately describes it.
3. Verify the one-sentence takeaway and every item under:
   `claims`, `method_components`, `experiment_records`, `limitations`,
   `ambiguities`, and `coverage`.
4. For all 38 selected experiment records, independently verify the exact value,
   unit, split/task/setting, method/checkpoint ownership, result role, full row and
   column header path, and cited evidence. A matching number in the wrong row or
   header is a failure. Use raw TeX for PaLM-E table structure and rendered PDF
   pages when visual grouping matters.
5. Check criticality labels. Identify material paper claims, components,
   experiments, limitations, or ambiguities that the candidate omitted. Remember
   that experiment selection is intentionally representative rather than an
   exhaustive baseline transcription.
6. Distinguish author-stated limitations from reviewer inference. Check that each
   ambiguity describes a real disclosure obligation and does not encode a false
   premise.
7. Apply the hard failures and quality gates from the rubric. Never infer a pass
   merely because an anchor string exists.

You may use local read-only shell commands, PDF rendering/text inspection, and
image inspection. Prefer primary-source page/table references. Keep quotations
short; paraphrase whenever possible.

## Report format

Return one self-contained Markdown report with these sections:

1. `Invocation and independence` -- repeat the model, effort, sandbox, and source
   restrictions in this contract. Do not claim you independently measured hidden
   runtime settings.
2. `Executive verdict` -- one overall verdict and one per case, each exactly one
   of `PASS`, `PASS_WITH_CORRECTIONS`, or `FAIL`.
3. `Asset verification` -- expected versus observed hashes, page counts, and any
   version concern.
4. `Findings` -- ordered by severity (`P0`, `P1`, `P2`, `P3`). Each finding must
   include case, YAML path or item ID, concrete problem, primary-source evidence,
   and an exact correction. Say `None` when there are no findings at a severity.
5. `Complete item ledger` -- for every candidate item in every required group,
   list its ID and one of `PASS`, `FAIL`, or `UNCLEAR`, plus a concise independently
   checked source locator. Do not collapse ranges of IDs or omit passing items.
6. `Completeness and criticality` -- omitted material content, over-selection,
   under-selection, and any criticality changes.
7. `Rubric decision` -- triggered hard failures, gate-level assessment, and whether
   the corpus can be used for model-development evaluation after listed fixes.
8. `Recommended corpus action` -- explicit patch instructions but no file edits.

This is a model-proxy audit, not human annotation. Even for a clean `PASS`, do not
recommend populating `human_reviewer`, `reviewed_at`, or changing the current
human-review status under the v1 policy. Instead state what the audit establishes
and what remains for a future human sign-off.
