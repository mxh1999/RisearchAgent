# VLFM Independent Model Review

## Invocation and independence

- Contract-specified model: `gpt-5.6-sol`
- Contract-specified reasoning effort: `max`
- Contract-specified sandbox: `read-only`
- Contract-specified session persistence: disabled
- Scope: only `2312.03275v1-standard` and its frozen local PDF.
- Factual authority: the frozen PDF only. The candidate YAML was treated as untrusted.
- No web search, alternate paper version, remote TeX, cached reading, parser output, prior review notes, or model memory was used as evidence.
- All seven PDF pages were rendered and inspected; Tables I and II were separately inspected at readable resolution.
- No repository files were edited.
- Hidden runtime settings were not independently measured; the settings above are repeated from the invocation contract.

## Executive verdict

| Scope | Verdict |
|---|---|
| Overall audit | `PASS_WITH_CORRECTIONS` |
| `2312.03275v1-standard` | `PASS_WITH_CORRECTIONS` |

The PDF asset, all 11 evidence anchors, and all 18 selected numeric cells, header paths, ownership labels, units, and result roles are correct. Corrections are required for configuration-specific PointNav wording, source linkage for task/protocol coverage, and unresolved baseline protocols.

## Asset verification

| Check | Expected | Observed | Result |
|---|---|---|---|
| Local asset | `data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/pdfs/2312.03275.pdf` | Present; 1,653,895 bytes | PASS |
| SHA256 | `07f1f60fae11be46c488c1fbf5581c8f6d44904ac39ebb6071050d44d731efce` | `07f1f60fae11be46c488c1fbf5581c8f6d44904ac39ebb6071050d44d731efce` | PASS |
| Page count | 7 | 7, independently reported by PDF metadata inspection and page parsing | PASS |
| Title | “VLFM: Vision-Language Frontier Maps for Zero-Shot Semantic Navigation” | Exact title on PDF page 1 | PASS |
| ArXiv identity/version | `2312.03275v1` | Internal page-1 stamp: `arXiv:2312.03275v1 [cs.RO] 6 Dec 2023` | PASS |

No version concern was found. The remote-TeX-availability statement was not checked because remote sources were prohibited and no TeX fixture belongs to this PDF-only case.

## Findings

### P0

None.

### P1

None.

### P2

#### P2-1 — PointNav dependency is not scoped to the simulated configuration

- **Case:** `2312.03275v1-standard`
- **YAML paths/items:** `reference.one_sentence_takeaway`; `vlfm-claim-modular-training-nuance`; `vlfm-method-waypoint-policy`; `vlfm-ambiguity-zero-shot`
- **Problem:** “the full system uses … a PointNav policy” can be read as applying to both Habitat and Spot. The paper explicitly uses the trained PointNav policy for simulated benchmarks but not for the real-world deployment.
- **Primary-source evidence:** PDF page 4, §IV.D states that PointNav was trained for 2.5 billion steps on HM3D and explicitly says it is not used for the real-world demonstrations. Page 6, §VI.C states that Spot instead uses the Boston Dynamics API for waypoint navigation and ZoeDepth for target-depth estimation.
- **Exact correction:**
  1. Replace “the full system uses” with “the Habitat benchmark configuration uses.”
  2. Add `vlfm-pdf-real-world` to `vlfm-claim-modular-training-nuance.evidence_refs`.
  3. Extend the claim and zero-shot disclosure to state: “The Spot deployment replaces PointNav with the BD waypoint API and adds ZoeDepth; it still uses pretrained perception components.”
  4. Scope `vlfm-method-waypoint-policy` to simulated benchmarks and add a noncritical real-world navigation component covering the BD API, ZoeDepth, gripper camera, and body depth cameras.

#### P2-2 — Coverage descriptions lack section-specific task and protocol evidence

- **Case:** `2312.03275v1-standard`
- **YAML paths/items:** `vlfm-area-problem`; `vlfm-area-primary-results`
- **Problem:** `vlfm-area-problem` claims coverage of the task definition but cites the Abstract and §IV overview rather than §III. `vlfm-area-primary-results` claims coverage of dataset protocols but cites only the Table I/§VI.A evidence entry rather than §V. The relevant facts are correct, but the evidence mappings are only partial.
- **Primary-source evidence:** PDF page 2, §III defines observations, actions, the 1 m success radius, and the 500-step limit. PDF page 5, §V states the validation splits and episode counts: Gibson 1,000, HM3D 2,000, and MP3D 2,195.
- **Exact correction:** Add:
  - `vlfm-pdf-problem-formulation`, page 2, §III, anchored at “An episode is defined as successfully completed,” covering observations, action space, success radius, and step limit.
  - `vlfm-pdf-experimental-setup`, page 5, §V, anchored at “We evaluate our approach using the Habitat simulator on the validation splits,” covering split and episode counts.

  Cite the first from `vlfm-area-problem`, the second from `vlfm-area-primary-results`, and both where experiment-record protocol fields require them.

#### P2-3 — Six baseline `protocol` fields refer to information that Table I does not report

- **Case:** `2312.03275v1-standard`
- **Items:** `vlfm-baseline-semutil-gibson-spl`, `vlfm-baseline-semutil-gibson-sr`, `vlfm-baseline-esc-hm3d-spl`, `vlfm-baseline-esc-hm3d-sr`, `vlfm-baseline-esc-mp3d-spl`, `vlfm-baseline-esc-mp3d-sr`
- **Problem:** Each uses `protocol: as reported in Table I`, but Table I reports dataset, semantic-navigation training, SPL, and SR—not the original baseline evaluation protocols. The frozen PDF does not establish whether every implementation detail of VLFM’s protocol applies to the cited baseline results.
- **Primary-source evidence:** PDF page 5, Table I and §V. Table I contains no protocol column; §V describes VLFM’s evaluation setup. The original baseline papers were not supplied and cannot be consulted under this audit.
- **Exact correction:** Replace each field with: `protocol: "Original baseline protocol not restated in the frozen PDF; value is reported only as a Table I benchmark comparison."` Add a noncritical baseline-protocol ambiguity warning against silently importing VLFM’s episode counts or implementation details into cited baseline rows.

### P3

#### P3-1 — Author-attributed scan-quality interpretation is omitted

- **Case:** `2312.03275v1-standard`
- **YAML path:** material completeness; related item `vlfm-ambiguity-cross-dataset`
- **Problem:** The candidate correctly warns against direct cross-dataset comparison but omits the authors’ stated interpretation that lower MP3D performance is partly associated with lower scan fidelity, while Gibson scenes were repaired.
- **Primary-source evidence:** PDF page 6, §VI.A, paragraph beginning “We also attribute the higher performance on the Gibson and HM3D datasets…”
- **Exact correction:** Add a noncritical evidence item anchored at “The MP3D dataset has significantly lower visual fidelity” and extend `vlfm-ambiguity-cross-dataset.expected_disclosure` with an explicitly attributed statement: “The authors attribute part of the difference to scan quality; this is their interpretation, not an independently established causal result.”

## Complete item ledger

### One-sentence takeaway

| Item | Status | Independently checked locator |
|---|---|---|
| `reference.one_sentence_takeaway` | UNCLEAR | PDF pp. 3–5 supports value-map selection, results, and simulated PointNav dependency; p. 6 shows Spot does not use PointNav. |

### Evidence entries

| ID | Status | Independently checked locator |
|---|---|---|
| `vlfm-pdf-abstract` | PASS | PDF p. 1, Abstract; exact occupancy-map/frontier anchor and headline result. |
| `vlfm-pdf-overview` | PASS | PDF p. 2, §IV opening; initialization, exploration, and goal-navigation phases. |
| `vlfm-pdf-value-map` | PASS | PDF p. 3, §IV.B; BLIP-2 similarity, two map channels, and maximum-value frontier. |
| `vlfm-pdf-value-fusion` | PASS | PDF p. 4, §IV.B; weighted update equations and four-step procedure. |
| `vlfm-pdf-detection` | PASS | PDF p. 4, §IV.C; YOLOv7/Grounding-DINO, Mobile-SAM, and depth projection. |
| `vlfm-pdf-pointnav` | PASS | PDF p. 4, §IV.D; HM3D training split, 2.5 billion steps, policy observations. |
| `vlfm-pdf-table-1` | PASS | PDF p. 5, Table I and §VI.A; caption, rows, headers, and comparison discussion. |
| `vlfm-pdf-table-2` | PASS | PDF p. 6, Table II and §VI.B; all three value-update rows and six metric columns. |
| `vlfm-pdf-single-floor-limit` | PASS | PDF p. 6, §VI.A; missing z-coordinate and 14.6%/9.6% failures. |
| `vlfm-pdf-real-world` | PASS | PDF p. 6, §VI.C; qualitative Spot deployment and RTX 4090 MaxQ setup. |
| `vlfm-pdf-conclusion-limits` | PASS | PDF p. 6, §VII; visibility and task-specific-map limitations. |

### Claims

| ID | Status | Independently checked locator |
|---|---|---|
| `vlfm-claim-value-guided-frontiers` | PASS | PDF pp. 2–3, §IV and §IV.B. |
| `vlfm-claim-zero-shot-results` | PASS | PDF p. 5, Table I and §VI.A; PIRLNav HM3D SR is 64.1 versus VLFM 52.5. |
| `vlfm-claim-weighted-update` | PASS | PDF p. 6, Table II and §VI.B; weighted averaging wins all six comparisons. |
| `vlfm-claim-modular-training-nuance` | UNCLEAR | PDF p. 4 supports the Habitat configuration; p. 6 contradicts an unscoped application to Spot. |
| `vlfm-claim-real-world-demonstration` | PASS | PDF p. 6, §VI.C; qualitative description with no episode-level quantitative protocol anywhere in the PDF. |

### Method components

| ID | Status | Independently checked locator |
|---|---|---|
| `vlfm-method-frontier-map` | PASS | PDF pp. 2–3, §IV.A; depth/odometry map and frontier midpoints. |
| `vlfm-method-value-map` | PASS | PDF p. 3, §IV.B; RGB/text similarity projected with confidence. |
| `vlfm-method-value-fusion` | PASS | PDF pp. 3–4, §IV.B and Fig. 3. |
| `vlfm-method-target-detection` | PASS | PDF p. 4, §IV.C. |
| `vlfm-method-waypoint-policy` | UNCLEAR | Correct for Habitat at p. 4, §IV.D, but needs simulation scope because p. 6, §VI.C uses the BD API instead. |

### Experiment records

| ID | Status | Independently checked locator |
|---|---|---|
| `vlfm-main-gibson-spl` | PASS | PDF p. 5, Table I, `VLFM (Ours)` → Gibson → SPL = 52.2; protocol context pp. 2 and 5. |
| `vlfm-main-gibson-sr` | PASS | PDF p. 5, Table I, `VLFM (Ours)` → Gibson → SR = 84.0; protocol context pp. 2 and 5. |
| `vlfm-main-hm3d-spl` | PASS | PDF p. 5, Table I, `VLFM (Ours)` → HM3D → SPL = 30.4; protocol context pp. 2 and 5. |
| `vlfm-main-hm3d-sr` | PASS | PDF p. 5, Table I, `VLFM (Ours)` → HM3D → SR = 52.5; protocol context pp. 2 and 5. |
| `vlfm-main-mp3d-spl` | PASS | PDF p. 5, Table I, `VLFM (Ours)` → MP3D → SPL = 17.5; protocol context pp. 2 and 5. |
| `vlfm-main-mp3d-sr` | PASS | PDF p. 5, Table I, `VLFM (Ours)` → MP3D → SR = 36.4; protocol context pp. 2 and 5. |
| `vlfm-baseline-semutil-gibson-spl` | UNCLEAR | PDF p. 5, Table I cell 40.5 is correct; original baseline protocol is not restated. |
| `vlfm-baseline-semutil-gibson-sr` | UNCLEAR | PDF p. 5, Table I cell 69.3 is correct; original baseline protocol is not restated. |
| `vlfm-baseline-esc-hm3d-spl` | UNCLEAR | PDF p. 5, Table I cell 22.3 is correct; original baseline protocol is not restated. |
| `vlfm-baseline-esc-hm3d-sr` | UNCLEAR | PDF p. 5, Table I cell 39.2 is correct; original baseline protocol is not restated. |
| `vlfm-baseline-esc-mp3d-spl` | UNCLEAR | PDF p. 5, Table I cell 14.2 is correct; original baseline protocol is not restated. |
| `vlfm-baseline-esc-mp3d-sr` | UNCLEAR | PDF p. 5, Table I cell 28.7 is correct; original baseline protocol is not restated. |
| `vlfm-ablation-weighted-gibson-spl` | PASS | PDF p. 6, Table II, `Weighted avg.` → Gibson → SPL = 52.2. |
| `vlfm-ablation-weighted-gibson-sr` | PASS | PDF p. 6, Table II, `Weighted avg.` → Gibson → SR = 84.0. |
| `vlfm-ablation-weighted-hm3d-spl` | PASS | PDF p. 6, Table II, `Weighted avg.` → HM3D → SPL = 30.4. |
| `vlfm-ablation-weighted-hm3d-sr` | PASS | PDF p. 6, Table II, `Weighted avg.` → HM3D → SR = 52.5. |
| `vlfm-ablation-weighted-mp3d-spl` | PASS | PDF p. 6, Table II, `Weighted avg.` → MP3D → SPL = 17.5. |
| `vlfm-ablation-weighted-mp3d-sr` | PASS | PDF p. 6, Table II, `Weighted avg.` → MP3D → SR = 36.4. |

### Limitations

| ID | Status | Independently checked locator |
|---|---|---|
| `vlfm-limit-single-floor` | PASS | PDF p. 6, §VI.A; author-stated, including both percentages. |
| `vlfm-limit-visible-target` | PASS | PDF p. 6, §VII; author-stated visibility and interactive-search limitation. |
| `vlfm-limit-task-specific-map` | PASS | PDF p. 6, §VII; author-stated sequential-task, VLN, and long-horizon limitation. |
| `vlfm-limit-real-world-evaluation` | PASS | PDF p. 6, §VI.C plus complete-PDF check; correctly labeled annotator inference. |

### Ambiguities

| ID | Status | Independently checked locator |
|---|---|---|
| `vlfm-ambiguity-zero-shot` | UNCLEAR | PDF p. 4 supports component-training disclosure; pp. 4 and 6 require simulator-versus-Spot scoping. |
| `vlfm-ambiguity-sota-scope` | PASS | PDF p. 5, Table I; PIRLNav exceeds VLFM on HM3D SR only. |
| `vlfm-ambiguity-dash` | PASS | PDF p. 5, Table I and §VI.A explicitly describe unfilled cells as unevaluated. |
| `vlfm-ambiguity-cross-dataset` | PASS | PDF p. 5, §V; distinct datasets, scene counts, episode counts, and category counts. |
| `vlfm-ambiguity-real-world` | PASS | PDF p. 6, §VI.C; qualitative deployment only. |

### Coverage

| Item | Status | Independently checked locator |
|---|---|---|
| `vlfm-area-problem` | FAIL | Pages 1–2 are correct, but the cited entries omit the relevant p. 2, §III task-definition anchor. |
| `vlfm-area-method` | PASS | PDF pp. 2–4, §IV.A–D. |
| `vlfm-area-primary-results` | UNCLEAR | Table I is correctly cited, but the p. 5, §V dataset-protocol evidence is not separately referenced. |
| `vlfm-area-ablation-and-limits` | PASS | PDF p. 6, Table II and §§VI.A–C, VII. |
| `coverage.optional_areas[0]` | PASS | PDF p. 7 contains only the remaining references. |

## Completeness and criticality

- **Material omissions:** simulator-versus-Spot navigation substitutions; explicit uncertainty about cited baseline protocols.
- **Noncritical omission:** the authors’ scan-quality interpretation for MP3D versus Gibson/HM3D.
- **Author versus reviewer provenance:** all three author-stated limitations and the real-world-evaluation annotator inference are classified correctly.
- **Experiment selection:** retain all 18 records. They fall within the 10–20 target, all cells are correct, and the numerically duplicated Table I/Table II values represent distinct table identities and result roles rather than accidental duplication.
- **Over-selection:** none.
- **Under-selection:** none material under the representative, non-exhaustive policy. The critical weighted-update claim directly covers the unselected comparator cells.
- **Criticality changes:** none required. Preserve critical status for the zero-shot disclosure and modular-training claim after scoping them. Any new baseline-protocol or scan-quality ambiguity should be noncritical.

## Rubric decision

### Hard failures

- `fabricated_or_unresolvable_evidence`: not triggered; all 11 anchors resolve on the claimed pages.
- `unsupported_critical_claim`: not triggered; the PointNav statement is supported for Habitat but requires scope clarification.
- `critical_numeric_error`: not triggered; all 18 values are exact.
- `silent_ambiguous_mapping`: not triggered; every table cell has the correct row, dataset, metric, method ownership, and result role.
- `wrong_result_ownership`: not triggered.
- `premature_finish`: not triggered as a model-run failure; the corpus remains explicitly `draft`.

### Gate-level assessment

| Gate/metric | Assessment |
|---|---|
| Evidence locator validity | PASS: 11/11 |
| Evidence entailment precision | Not yet certifiable at 0.95 because the critical component-training claim lacks configuration scope |
| Primary experiment precision | Numeric/header/ownership precision is 12/12; normalized exact-field precision is not certifiable for six baseline protocols |
| Primary experiment recall | PASS: all 12 selected primary records are present |
| Exact numeric value accuracy | PASS: 18/18 |
| Header-to-cell mapping accuracy | PASS: 18/18 |
| Result-role classification | PASS: 18/18 |
| Silent ambiguous mappings | PASS: 0 |
| Required-area coverage | Semantic coverage is 4/4; two coverage-to-evidence mappings require correction |
| Ambiguity disclosure recall | Not yet complete because baseline-protocol uncertainty is absent and zero-shot scope is partial |
| Premature-finish rate | Not measurable from this reference audit |

A model-run 100-point score is not reported because no model reading submission or operational trace was supplied. The current draft should not be used as gold evaluation data. After the listed corrections, re-audit, and required human verification, it is technically suitable for model-development evaluation.

## Recommended corpus action

1. Scope all PointNav dependency language to Habitat and document the BD API/ZoeDepth Spot path.
2. Add dedicated §III task-definition and §V experimental-setup evidence entries and attach them to the corresponding coverage and protocol-bearing records.
3. Replace the six baseline protocol placeholders with explicit source-limited uncertainty and add a noncritical ambiguity item.
4. Add the author-attributed scan-quality caveat without presenting it as independently proven causality.
5. Keep all 18 selected experiment cells and their current numeric values, header paths, ownership, result kinds, and criticality labels.
6. Re-run structural and asset validation, then perform human review of the patched candidate.

This model-proxy audit must not populate `human_reviewer`, set `reviewed_at`, or change `review.status` from `draft`; those remain reserved for future human sign-off.
