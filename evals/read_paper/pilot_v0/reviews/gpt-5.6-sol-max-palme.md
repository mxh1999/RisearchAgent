# Invocation and independence

- Contract-declared model: `gpt-5.6-sol`
- Contract-declared reasoning effort: `max`
- Contract-declared sandbox: `read-only`
- Contract-declared session persistence: disabled
- Audit scope: only `2303.03378v1-standard` and all 20 experiment records.
- Factual authorities: the frozen 18-page PDF and frozen `main.tex`. Policy files were used only as policy.
- No web search, alternate paper version, cached deep reading, prior reviewer notes, or model memory was used as evidence. Programmatic PDF extraction was used only for locating content; dense tables were checked against rendered PDF regions and raw TeX.
- Hidden runtime settings were not independently measured.

# Executive verdict

| Scope | Verdict | Rationale |
|---|---|---|
| Overall | `PASS_WITH_CORRECTIONS` | All 20 numeric values, units, table cells, header mappings, ownership assignments, and result roles are correct. Corrections are required for Table 2 protocol evidence and Task 1 split disclosure, one material method omission, one invalid evidence section locator, and several completeness items. |
| `2303.03378v1-standard` | `PASS_WITH_CORRECTIONS` | No critical numeric, ownership, or task/demo-count mapping error was found, but the candidate is not ready for evaluation use as written. |

# Asset verification

| Asset | Expected | Observed | Result |
|---|---|---|---|
| PDF `data/2026-06-03/pdfs/2303.03378.pdf` | SHA256 `535cc3c7fe1ae7428b9ac7d6a3738a0529975aadc372b2229ea0cb2ce724576a`; 18 pages | Same SHA256; 18 pages | Match |
| E-print archive `2303.03378v1.eprint` | SHA256 `cad9ecfc8a561588b3431719b093ae8efca05f49881c95822bd3b358fe4be3b9` | Same SHA256 | Match |
| Frozen `main.tex` | SHA256 `5031560212451f3cea5d60458a90d6af937648a709ea3d5f62365d4e31a69add` | Same SHA256 | Match |
| Archive/source consistency | Archive member should match frozen source | Archive `main.tex` and extracted `main.tex` are byte-identical | Match |
| Paper identity/version | PaLM-E, ArXiv `2303.03378v1` | Visible title and authors match; PDF page 1 carries `arXiv:2303.03378v1 [cs.LG] 6 Mar 2023` | Match |

The PDF metadata contains generic submission-template fields (`Anonymous Submission`, blank title, ICML 2022 subject), but these do not conflict with the visible title, authors, ArXiv stamp, hashes, or frozen source. No version concern remains.

# Findings

## P0

None.

## P1

### P1-1 - Table 2 protocols lack their controlling evidence, and Task 1 silently resolves contradictory split terminology

- Case: `2303.03378v1-standard`
- YAML items:
  - `palme-t2-12b-single-task1-10`
  - `palme-t2-12b-frozen-task2-40`
  - `palme-t2-12b-unfrozen-task2-40`
  - `palme-t2-12b-taskft-task2-20`
  - `palme-t2-84b-task1-40`
  - `palme-t2-84b-task3-80`
- Problem: Their Table 2 cells and row/column paths are correct, but the cited page 9 table and TeX lines 479-504 do not establish Task 1 validation/test protocol or the 80-rollout protocol for Tasks 2 and 3. Moreover, the paper says Task 1 uses a “test-set” while reporting “validation accuracy”; the two Task 1 records silently set `split: validation`.
- Primary-source evidence: PDF page 16, Section B.2, anchor `Train and Evaluation.` It states that Tasks 2 and 3 use 80 rollouts and that Task 1 uses a test set while reporting validation accuracy.
- Exact correction:
  1. Add evidence item `palme-pdf-language-table-evaluation` for PDF page 16, Section B.2, anchor `Train and Evaluation.`.
  2. Add that evidence reference to all six records.
  3. Change the two Task 1 records to `split: test` or an explicitly unresolved normalized value such as `paper_test_set`; retain `metric: validation_accuracy`.
  4. Update their protocol text to preserve the paper's inconsistent terminology.
  5. Add a critical ambiguity requiring disclosure of the Task 1 test-set/validation-accuracy mismatch.

### P1-2 - The material entity-referral mechanism is omitted

- Case: `2303.03378v1-standard`
- YAML path: `reference.method_components` and associated claims/coverage
- Problem: The candidate omits entity-labeling multimodal tokens, even though the introduction identifies them as a novel architectural contribution and they are necessary for object-centric plans to refer to otherwise indistinguishable objects.
- Primary-source evidence: PDF page 3 contribution list; PDF page 5, `Entity referrals`; PDF page 15 TAMP prompt construction; `main.tex` lines 327-335. Table 7 on PDF page 16 also compares state models with and without entity referrals.
- Exact correction: Add a critical method component describing `<obj_j>` token labeling, generated object references, and the assumption that low-level policies understand those tokens. Add a critical claim or expand architecture coverage to capture this stated contribution.

## P2

### P2-1 - `palme-pdf-contributions` has the wrong section identity and leaves page 2 out of required coverage

- Case: `2303.03378v1-standard`
- YAML items: `palme-pdf-contributions`, `palme-area-problem-and-claims`
- Problem: The page 3 anchor `demonstrate positive transfer across different tasks` occurs in Section 2, `Actions-output models`, not Section 1. Its note overstates it as the paper's stated contribution list. The actual contribution list begins on PDF page 2 and continues on page 3, but page 2 is absent from required coverage.
- Primary-source evidence: PDF page 2, Section 1, anchor `To summarize our main contributions`; continuation on PDF page 3.
- Exact correction: Move or replace `palme-pdf-contributions` with the page 2 Section 1 anchor, state that the list continues on page 3, and change `palme-area-problem-and-claims.pages` to `[1, 2, 3]`.

### P2-2 - The author-stated robotics cost of freezing the LLM is omitted

- Case: `2303.03378v1-standard`
- YAML path: `reference.limitations`
- Problem: The candidate records freezing as a remedy for language forgetting but omits the author's stated countervailing limitation that frozen-LLM training sometimes struggles on robotics tasks.
- Primary-source evidence: PDF page 10, Section 7, `Retaining language capabilities`; Table 2's matched frozen/unfrozen rows on PDF page 9, including 36.3 versus 57.5 for Task 2 at 40 demonstrations.
- Exact correction: Add a critical `author_stated` limitation explaining that freezing preserves inherited language performance but can reduce robotics performance, citing `palme-pdf-discussion`, `palme-pdf-table-2`, and the new page 16 protocol evidence.

### P2-3 - The two OSRT Table 1 rows are not represented as a required ambiguity

- Case: `2303.03378v1-standard`
- YAML path: `reference.ambiguities`
- Problem: Table 1 contains both `OSRT (no VQA)` at 71.9/75.1 and `OSRT` at 82.5/76.2. The selected records correctly use the latter, but `training_mixture: no_large_scale_VQA` can still be confused with the explicitly named no-VQA row.
- Primary-source evidence: PDF page 8, Table 1; PDF page 7 discussion; `main.tex` lines 462-463. The paper explains that removing TAMP VQA leaves only 640 planning examples and causes the smaller result.
- Exact correction: Add a critical ambiguity distinguishing “no TAMP VQA” from “no large-scale mixture.” Make the selected OSRT records explicitly state that TAMP VQA is included and that the selected row is `OSRT`, not `OSRT (no VQA)`.

## P3

### P3-1 - Table 1 contains an undisclosed internal freezing inconsistency

- Case: `2303.03378v1-standard`
- YAML path: `reference.ambiguities`, with impact on `palme-t1-state-no-pretrain-p1`
- Problem: The Table 1 caption first says all experiments freeze the LLM, then gives an exception for the non-pretrained case. The candidate protocol follows the specific exception, but the source inconsistency is not disclosed.
- Primary-source evidence: PDF page 8, Table 1 caption; `main.tex` line 473.
- Exact correction: Add a noncritical ambiguity preserving both statements and explaining that the candidate follows the explicit exception. Optionally add `llm_frozen: false` to the non-pretrained record's structured setting.

# Complete item ledger

## One-sentence takeaway

| Item | Status | Independently checked locator |
|---|---|---|
| `reference.one_sentence_takeaway` | `PASS` | PDF pp. 1, 4, 7-10, and 17 support token interleaving, cross-domain transfer, and improved retention with scale. |

## Evidence

| ID | Status | Independently checked locator |
|---|---|---|
| `palme-pdf-abstract` | `PASS` | PDF p. 1, Abstract; visual line wrapping splits “continuous,” but the anchor and note are accurate. |
| `palme-pdf-contributions` | `FAIL` | PDF p. 3 contains the anchor, but it is in Section 2 rather than Section 1; the main contribution list starts on p. 2. |
| `palme-pdf-architecture` | `PASS` | PDF p. 4, Section 3, multimodal-sentence subsection and Eq. 3. |
| `palme-pdf-control-loop` | `PASS` | PDF p. 4, `Embodying the output`; text generation, low-level policies, and replanning are explicit. |
| `palme-pdf-input-representations` | `PASS` | PDF p. 5, Section 4; state, ViT, object-centric, and OSRT representations. |
| `palme-pdf-training` | `PASS` | PDF p. 5, Section 5; composite sizes and freezing setup. |
| `palme-pdf-cotraining` | `PASS` | PDF p. 6, Section 5; full mixture and 8.9% embodied-data proportion. |
| `palme-pdf-tamp-analysis` | `PASS` | PDF p. 7, Section 6.2; ViT-4B full-mixture transfer and OSRT interpretation. |
| `palme-pdf-table-1` | `PASS` | PDF p. 8, Table 1; rendered rows and grouped headers verified. |
| `palme-pdf-real-robot` | `PASS` | PDF p. 8, Section 6.4; explicitly qualitative real-kitchen evaluation. |
| `palme-pdf-table-2` | `PASS` | PDF p. 9, Table 2; rendered task/demo groupings verified. |
| `palme-pdf-table-4` | `PASS` | PDF p. 9, Table 4; both result columns are F1. |
| `palme-pdf-table-5` | `PASS` | PDF p. 9, Table 5; generalist and task-specific groups are visually distinct. |
| `palme-pdf-retention` | `PASS` | PDF p. 9, Section 6.6 and Figure 6. |
| `palme-pdf-discussion` | `PASS` | PDF p. 10, Section 7, `Retaining language capabilities`. |
| `palme-pdf-table-7` | `PASS` | PDF p. 16, Table 7; in-distribution, object-count, and OOD groups. |
| `palme-pdf-table-8` | `PASS` | PDF p. 17, Table 8; unfrozen column groups and relative deltas verified. |
| `palme-pdf-tables-9-10` | `PASS` | PDF p. 18, Tables 9-10; precision, recall, and F1 decomposition. |
| `palme-tex-table-1` | `PASS` | `main.tex` lines 444-477, label `tab:damp_one_percent_data`. |
| `palme-tex-table-2` | `PASS` | `main.tex` lines 479-534, label `tab:lt_sim`; task/demo headers verified. |
| `palme-tex-table-4` | `PASS` | `main.tex` lines 581-608, label `table:fractal_sd`. |
| `palme-tex-table-5` | `PASS` | `main.tex` lines 642-673, label `table:general-visual-language`. |
| `palme-tex-table-8` | `PASS` | `main.tex` lines 898-935, label `tab:general-language`. |

## Claims

| ID | Status | Independently checked locator |
|---|---|---|
| `palme-claim-multimodal-token-injection` | `PASS` | PDF p. 4, Eq. 3 and surrounding Section 3 text. |
| `palme-claim-text-control-boundary` | `PASS` | PDF p. 4, robot control-loop subsection. |
| `palme-claim-cross-domain-transfer` | `PASS` | PDF pp. 7-8, Table 1; TeX lines 460-461 confirm 30.6/74.1 and 32.9/74.6. |
| `palme-claim-osrt-data-efficiency` | `PASS` | PDF pp. 7-8, Table 1; TeX line 463 confirms 82.5/76.2. |
| `palme-claim-generalist-okvqa` | `PASS` | PDF p. 9, Table 5; TeX line 653 confirms generalist 66.1. |
| `palme-claim-scale-retention` | `PASS` | PDF pp. 9 and 17, Table 8; TeX line 929 confirms -87.3% and -3.8%. |
| `palme-claim-real-robot-scope` | `PASS` | PDF p. 8 explicitly calls the evaluation qualitative and reports disturbances without aggregate success statistics. |

## Method components

| ID | Status | Independently checked locator |
|---|---|---|
| `palme-method-modality-encoders` | `PASS` | PDF p. 5, Section 4. |
| `palme-method-multimodal-sentence` | `PASS` | PDF p. 4, multimodal-sentence subsection. |
| `palme-method-decoder` | `PASS` | PDF p. 4, decoder-only LLM description. |
| `palme-method-training` | `PASS` | PDF pp. 5-6, Section 5. |
| `palme-method-control-loop` | `PASS` | PDF p. 4, control-loop subsection. |

## Experiment records

| ID | Status | Independently checked locator |
|---|---|---|
| `palme-t1-state-no-pretrain-p1` | `PASS` | PDF p. 8 Table 1; TeX line 457: State, GT, no pretraining, p1 = 45.0. |
| `palme-t1-state-pretrained-p1` | `PASS` | PDF p. 8 Table 1; TeX line 458: State, GT, pretrained, p1 = 55.9. |
| `palme-t1-vit4b-single-p1` | `PASS` | PDF p. 8 Table 1; TeX line 460: ViT-4B single robot, p1 = 30.6. |
| `palme-t1-vit4b-full-p1` | `PASS` | PDF p. 8 Table 1; TeX line 461: ViT-4B full mixture, p1 = 74.1. |
| `palme-t1-vit4b-single-p2` | `PASS` | PDF p. 8 Table 1; TeX line 460: p2 = 32.9. |
| `palme-t1-vit4b-full-p2` | `PASS` | PDF p. 8 Table 1; TeX line 461: p2 = 74.6. |
| `palme-t1-osrt-p1` | `PASS` | PDF p. 8 Table 1; TeX line 463, `OSRT` row, p1 = 82.5. |
| `palme-t1-osrt-p2` | `PASS` | PDF p. 8 Table 1; TeX line 463, `OSRT` row, p2 = 76.2. |
| `palme-t2-12b-single-task1-10` | `FAIL` | PDF p. 9/TeX line 494 confirm 20.0; PDF p. 16 supplies the uncited protocol and calls the split a test set, not an unqualified validation split. |
| `palme-t2-12b-frozen-task2-40` | `FAIL` | PDF p. 9/TeX line 495 confirm frozen, no task finetuning, Task 2/40 = 36.3; 80-rollout evidence is only on p. 16 and is not cited. |
| `palme-t2-12b-unfrozen-task2-40` | `FAIL` | PDF p. 9/TeX line 496 confirm unfrozen Task 2/40 = 57.5; p. 16 protocol evidence is missing from refs. |
| `palme-t2-12b-taskft-task2-20` | `FAIL` | PDF p. 9/TeX line 497 confirm task-finetuned Task 2/20 = 58.8; p. 16 protocol evidence is missing from refs. |
| `palme-t2-84b-task1-40` | `FAIL` | PDF p. 9/TeX line 498 confirm Task 1/40 = 90.0; p. 16 uses test-set/validation-accuracy terminology that the record silently resolves. |
| `palme-t2-84b-task3-80` | `FAIL` | PDF p. 9/TeX line 498 confirm Task 3/80 = 64.4; p. 16 protocol evidence is missing from refs. |
| `palme-t4-failure-full-frozen-f1` | `PASS` | PDF p. 9 Table 4; TeX line 598 and PDF p. 18 Table 9 confirm frozen full-mixture F1 = 0.91. |
| `palme-t4-affordance-full-unfrozen-f1` | `PASS` | PDF p. 9 Table 4; TeX line 599 and PDF p. 18 Table 10 confirm unfrozen full-mixture F1 = 0.91. |
| `palme-t5-562b-okvqa` | `PASS` | PDF p. 9 Table 5; TeX line 653: generalist PaLM-E-562B, OK-VQA val = 66.1. |
| `palme-t5-562b-vqav2` | `PASS` | PDF p. 9 Table 5; TeX line 653: generalist PaLM-E-562B, VQAv2 test-dev = 80.0. |
| `palme-t8-12b-nlg-delta` | `PASS` | PDF p. 17 Table 8; TeX line 929: PaLM-E-12B unfrozen NLG relative delta = -87.3%. |
| `palme-t8-562b-nlg-delta` | `PASS` | PDF p. 17 Table 8; TeX line 929: PaLM-E-562B unfrozen NLG relative delta = -3.8%. |

## Limitations

| ID | Status | Independently checked locator |
|---|---|---|
| `palme-limit-low-level-policy` | `PASS` | PDF p. 4; PaLM-E sequences assumed low-level skills rather than direct motor actions. |
| `palme-limit-language-forgetting` | `PASS` | PDF pp. 9-10 and 17; forgetting and both mitigation paths are author-stated. |
| `palme-limit-real-robot-quantification` | `PASS` | PDF p. 8; correctly marked annotator inference from an explicitly qualitative evaluation. |
| `palme-limit-compute-scale` | `PASS` | PDF p. 5 composite sizing and p. 9 Table 5; absence of deployment latency analysis is correctly marked inference. |

## Ambiguities

| ID | Status | Independently checked locator |
|---|---|---|
| `palme-ambiguity-composite-size` | `PASS` | PDF p. 5 gives 8B+4B, 62B+22B, and 540B+22B conventions. |
| `palme-ambiguity-table-2-header` | `PASS` | Rendered PDF p. 9 and TeX lines 486-498 confirm three task groups and their demo subcolumns. |
| `palme-ambiguity-dash` | `PASS` | Tables 1-2 distinguish printed `0.0` from dashes. |
| `palme-ambiguity-frozen-row` | `PASS` | Table 2 has otherwise similar frozen and unfrozen full-mixture rows. |
| `palme-ambiguity-table-4-metric` | `PASS` | Table 4 caption says F1; Tables 9-10 provide precision/recall. |
| `palme-ambiguity-generalist-checkpoint` | `PASS` | Table 5 caption explicitly distinguishes one generalist checkpoint from separate task-specific checkpoints. |
| `palme-ambiguity-real-robot` | `PASS` | PDF p. 8 explicitly describes qualitative evaluation. |
| `palme-ambiguity-rounded-language-drop` | `PASS` | Figure 6/text round to 3.9%; Table 8 gives exact -3.8% NLG relative delta. |

## Coverage

| ID/path | Status | Independently checked locator |
|---|---|---|
| `palme-area-problem-and-claims` | `FAIL` | PDF p. 2 contains substantial introduction content and the start of the main contribution list but is omitted; its contribution evidence is mis-sectioned. |
| `palme-area-architecture` | `PASS` | PDF pp. 4-5 cover injection, decoder/output boundary, and modality encoders. |
| `palme-area-training` | `PASS` | PDF pp. 5-6 cover sizes, freezing, mixture, and experimental design. |
| `palme-area-embodied-results` | `PASS` | PDF pp. 7-9 cover TAMP, Language-Table, mobile manipulation, and qualitative robot results. |
| `palme-area-generalist-and-retention` | `PASS` | PDF pp. 9-10 and 17 cover Table 5, retention discussion, and Table 8. |
| `palme-area-appendix-validation` | `PASS` | PDF pp. 16-18 contain Tables 7-10 as described. |
| `palme-area-tex-resolution` | `PASS` | All five listed TeX spans and labels resolve exactly. |
| `reference.coverage.optional_areas[0]` | `PASS` | PDF pp. 11-13 are references. |
| `reference.coverage.optional_areas[1]` | `PASS` | PDF pp. 14-15 contain Figure 7, the full-mixture inventory, and environment details. |

# Completeness and criticality

- Material omissions:
  - Entity referrals as a stated architectural contribution and method component.
  - The author-stated robotics-performance cost of freezing the LLM.
  - Task 1's test-set/validation-accuracy terminology ambiguity.
  - The distinction between `OSRT (no VQA)` and `OSRT`.
  - The internally inconsistent Table 1 freezing caption.
  - Required coverage of PDF page 2 and explicit evidence for the page 16 Language-Table evaluation protocol.

- Experiment selection:
  - All 20 selected numeric cells are correct.
  - No required numeric cell, ownership, or table-header correction is needed.
  - Twenty records already reach the annotation policy's upper target, so adding Table 7 cells is not required. If quantitative entity-referral coverage is desired, replace lower-priority noncritical records rather than exceeding 20.
  - No material over-selection was found.

- Criticality changes:
  - Add entity referrals as a critical method component and preferably a critical claim.
  - Add the frozen-LLM robotics tradeoff as a critical limitation.
  - Add the Task 1 split terminology ambiguity as critical because it affects a critical experiment record.
  - Add the OSRT row distinction as critical because conflation would change critical numeric results.
  - Add the Table 1 freezing-caption inconsistency as noncritical.
  - No existing item requires demotion or experiment-record criticality change.

# Rubric decision

## Hard failures

None triggered.

- No fabricated or nonexistent evidence location supports a critical numeric conclusion.
- No unsupported critical claim was found.
- No selected numeric value is wrong.
- No task/demo-count cell is shifted.
- No baseline/proposed-method ownership error was found.
- The Task 1 issue is a split-disclosure problem, not a numeric table-cell mapping error.

## Gate-level assessment

| Gate/dimension | Assessment |
|---|---|
| Evidence locator validity | `FAIL`: 22/23 evidence entries have correct page/section identity; `palme-pdf-contributions` does not. |
| Evidence entailment precision | `PASS` for the seven listed claims; all are supported by their primary sources. |
| Full-field experiment evidence | `FAIL`: all six Table 2 records omit the page 16 evidence needed for their split/protocol fields. |
| Primary experiment precision | `FAIL` under conservative exact-field matching: 14/16 primary records are fully correct; two Task 1 records silently misstate or resolve the split. |
| Primary experiment identity/value recall | `PASS`: all 16 selected primary record identities and values are present. |
| Exact numeric value accuracy | `PASS`: 20/20. |
| Header-to-cell mapping accuracy | `PASS`: 20/20. |
| Result ownership/role accuracy | `PASS`: 20/20. |
| Silent numeric/header ambiguity count | `PASS`: zero incorrect numeric mappings. |
| Ambiguity disclosure recall | `FAIL`: Task 1 terminology, OSRT row identity, and the Table 1 freezing inconsistency are absent. |
| Required-area coverage | `FAIL`: page 2 and the material entity-referral component are under-covered. |
| Completion validity | `FAIL` until the listed corrections are applied. |
| Premature-finish operational rate | Not measurable from a candidate reference audit. |

The case must not be used as-is. After correction, it is suitable as a draft model-development/calibration reference. It must not be treated as reviewed gold or used for acceptance gates until a future human reviewer performs the v1 sign-off.

# Recommended corpus action

1. Correct `palme-pdf-contributions` and expand `palme-area-problem-and-claims` to pages `[1, 2, 3]`.
2. Add a page 16 Language-Table evaluation evidence item and attach it to all six Table 2 records.
3. Correct the two Task 1 split fields and add the test-set/validation-accuracy ambiguity.
4. Add critical entity-referral method/claim coverage.
5. Add the author-stated frozen-LLM robotics tradeoff limitation.
6. Add OSRT-row and Table 1 freezing-caption ambiguities; make the selected OSRT setting explicitly distinguish TAMP VQA from large-scale VQA data.
7. Re-run structural and asset validation after patching:
   `conda run -n paper_reader python -m evals.read_paper.validation evals/read_paper/pilot_v0/manifest.yaml --check-assets`
8. Keep `review.status: draft`, `human_reviewer: null`, and `reviewed_at: null`. This model-proxy audit does not constitute human sign-off.

No repository file was edited.