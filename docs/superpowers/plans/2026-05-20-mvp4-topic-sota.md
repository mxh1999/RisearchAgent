# MVP-4 Topic SOTA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a topic-scoped SOTA updater that converts staged reading package experiment records into a raw ledger, an incremental setting-group registry, and `sota.md`.

**Architecture:** Add topic SOTA modules under `src/survey/` because MVP-4 operates on survey topic artifacts rather than the older global SOTA tracker. The workflow stores raw records in JSONL, uses an incremental cached setting registry to avoid full-history LLM calls, renders deterministic markdown from canonical groups, and writes stable topic artifacts without touching `topic.yaml`.

**Tech Stack:** Python dataclasses, existing `PaperReadingPackage` / `ExperimentRecord`, existing `TopicArtifactManager.update_auto_block`, pytest.

---

## File Structure

- Create `src/survey/sota_models.py`: topic SOTA record dataclass, grouping key helpers, setting group dataclasses, and conversion from reading packages.
- Create `src/survey/sota_normalizer.py`: incremental setting canonicalization with lexical top-k candidate retrieval and optional LLM decisions.
- Create `src/survey/sota_renderer.py`: render grouped SOTA records into markdown tables using canonical setting groups.
- Create `src/survey/sota_cli.py`: command handler for `python run.py sota update --topic ...`.
- Modify `src/survey/artifacts.py`: ensure `sota.md` exists without rewriting `topic.yaml`.
- Modify `run.py`: add `sota update` subcommand while preserving the old `python run.py sota` behavior.
- Test `tests/survey/test_sota_models.py`: normalization, conversion, JSONL.
- Test `tests/survey/test_sota_normalizer.py`: registry round-trip, exact matching, conservative grouping, LLM merge/create validation.
- Test `tests/survey/test_sota_renderer.py`: sorted markdown and warning rendering.
- Test `tests/survey/test_sota_cli.py`: parser/workflow/path safety/topic preservation.

---

### Task 1: Topic SOTA Models and Registry Types

**Files:**
- Create: `src/survey/sota_models.py`
- Test: `tests/survey/test_sota_models.py`

- [ ] **Step 1: Write failing tests**

Create tests that build two reading packages with experiment records and assert:

- whitespace normalization;
- empty setting becomes `N/A`;
- records are sorted by benchmark, setting, metric, value direction, method, paper id;
- JSONL round-trip preserves source evidence fields.
- setting group registry JSON round-trip preserves comparison axes and raw benchmark/settings.

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest tests/survey/test_sota_models.py -q
```

Expected: fail because `src.survey.sota_models` does not exist.

- [ ] **Step 3: Implement models**

Implement:

- `TopicSOTARecord` with deterministic `record_id`
- `RawBenchmarkSetting`
- `SettingGroup`
- `SettingGroupRegistry`
- `collect_sota_records(packages: list[PaperReadingPackage]) -> list[TopicSOTARecord]`
- `sort_sota_records(records: list[TopicSOTARecord]) -> list[TopicSOTARecord]`
- `records_to_jsonl(records: list[TopicSOTARecord]) -> str`
- `records_from_jsonl(text: str) -> list[TopicSOTARecord]`
- `setting_registry_to_json(registry: SettingGroupRegistry) -> str`
- `setting_registry_from_json(text: str) -> SettingGroupRegistry`

- [ ] **Step 4: Run GREEN**

Run:

```bash
python -m pytest tests/survey/test_sota_models.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/survey/sota_models.py tests/survey/test_sota_models.py
git commit -m "feat: add topic SOTA records"
```

---

### Task 2: Incremental Setting Normalizer

**Files:**
- Create: `src/survey/sota_normalizer.py`
- Test: `tests/survey/test_sota_normalizer.py`

- [ ] **Step 1: Write failing tests**

Create tests asserting:

- exact raw `(benchmark, setting)` match reuses an existing high-confidence group without calling the LLM;
- conservative mode creates one new group per unseen raw setting;
- LLM high-confidence `merge_existing` merges into a known candidate group;
- LLM medium-confidence `merge_existing` creates a separate group instead of merging;
- malformed LLM action or unknown `group_id` raises `ValueError`.

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest tests/survey/test_sota_normalizer.py -q
```

Expected: fail because `src.survey.sota_normalizer` does not exist.

- [ ] **Step 3: Implement normalizer**

Implement:

- `SettingCanonicalizer`
- `assign_setting_groups(records, registry, topic, llm=None, model=None, use_llm=True) -> SettingGroupRegistry`
- lexical top-k candidate retrieval over `canonical_benchmark`, `canonical_setting`, and raw settings;
- LLM prompt that includes only topic summary, one raw setting, sample record evidence, and top-k candidate groups;
- schema validation for `action`, `group_id`, `confidence`, `comparison_axes`, and rationale.

- [ ] **Step 4: Run GREEN**

Run:

```bash
python -m pytest tests/survey/test_sota_normalizer.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/survey/sota_normalizer.py tests/survey/test_sota_normalizer.py
git commit -m "feat: add incremental SOTA setting normalization"
```

---

### Task 3: SOTA Markdown Renderer

**Files:**
- Create: `src/survey/sota_renderer.py`
- Test: `tests/survey/test_sota_renderer.py`

- [ ] **Step 1: Write failing tests**

Create tests asserting:

- one benchmark section;
- one table per `(canonical setting, metric)`;
- higher-is-better tables sort descending;
- lower-is-better tables sort ascending;
- evidence includes page, section, and truncated quote;
- mixed `higher_is_better` values render a warning;
- low/medium confidence setting groups render confidence/rationale warnings;
- raw setting appears in the evidence column.

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest tests/survey/test_sota_renderer.py -q
```

Expected: fail because renderer does not exist.

- [ ] **Step 3: Implement renderer**

Implement:

- `render_sota_markdown(records: list[TopicSOTARecord], registry: SettingGroupRegistry) -> str`

Use ASCII arrows in headings: `higher is better` or `lower is better` text instead of Unicode arrows, to keep generated artifacts portable.

- [ ] **Step 4: Run GREEN**

Run:

```bash
python -m pytest tests/survey/test_sota_renderer.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/survey/sota_renderer.py tests/survey/test_sota_renderer.py
git commit -m "feat: render topic SOTA markdown"
```

---

### Task 4: SOTA CLI Workflow

**Files:**
- Create: `src/survey/sota_cli.py`
- Modify: `src/survey/artifacts.py`
- Modify: `run.py`
- Test: `tests/survey/test_sota_cli.py`

- [ ] **Step 1: Write failing tests**

Create tests asserting:

- `build_parser().parse_args(["sota", "update", "--topic", "..."])` parses `sota_command == "update"`;
- `build_parser().parse_args(["sota", "update", "--topic", "...", "--no-llm-normalize"])` sets conservative mode;
- `build_parser().parse_args(["sota"])` still parses old show mode;
- `cmd_sota_update(args)` writes `sota.md`, `state/sota_records.jsonl`, and `state/sota_setting_groups.json`;
- manual text around `AUTO:sota` is preserved;
- `topic.yaml` bytes are unchanged;
- mismatched `topic_id` fails before writes;
- packages with no experiments fail before writes.
- local topic/readings validation happens before Gemini import/API key checks.

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest tests/survey/test_sota_cli.py -q
```

Expected: fail because parser and CLI handler are not implemented.

- [ ] **Step 3: Implement CLI**

Implement:

- `cmd_sota_update(args) -> None`
- `_load_topic` and `_validate_topic_path` reuse from `src.survey.cli`
- default readings dir is `<topic_dir>/papers`
- output paths are `<topic_dir>/sota.md` and `<topic_dir>/state/sota_records.jsonl`
- setting registry path is `<topic_dir>/state/sota_setting_groups.json`
- use `TopicArtifactManager.ensure_topic_artifacts(topic)` and a new `ensure_sota_artifact(topic)` helper.
- if `--no-llm-normalize` is absent and unseen settings require LLM, load Gemini after local validations.

Modify `run.py`:

- replace the simple `sota` parser with optional subcommands;
- dispatch `sota update` before loading global config;
- preserve old `sota` no-subcommand path.

- [ ] **Step 4: Run GREEN**

Run:

```bash
python -m pytest tests/survey/test_sota_cli.py -q
python -m pytest tests/survey -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add run.py src/survey/artifacts.py src/survey/sota_cli.py tests/survey/test_sota_cli.py
git commit -m "feat: add topic SOTA update CLI"
```

---

### Task 5: Smoke and Final Verification

**Files:**
- No tracked files expected unless tests reveal a bug.

- [ ] **Step 1: Run real smoke**

Run:

```bash
python run.py sota update --topic data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/topic.yaml --no-llm-normalize
python run.py sota update --topic data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/topic.yaml
```

Expected:

- prints `SOTA: ...\sota.md`
- prints `Records: ...\state\sota_records.jsonl`
- prints `Setting groups: ...\state\sota_setting_groups.json`
- `topic.yaml` hash remains unchanged.

- [ ] **Step 2: Inspect generated artifacts**

Run:

```bash
Get-Content data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/sota.md -TotalCount 120
Get-Content data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/state/sota_records.jsonl -TotalCount 5
Get-Content data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/state/sota_setting_groups.json -TotalCount 80
```

Expected: markdown contains benchmark tables and JSONL contains records with evidence fields.

- [ ] **Step 3: Full verification**

Run:

```bash
python -m pytest -q
python -m compileall src run.py
python -c "import src.survey.sota_cli; import src.survey.sota_models; import src.survey.sota_renderer"
git status --short --branch
```

Expected:

- tests pass;
- compile/import commands exit 0;
- tracked worktree is clean except ignored smoke data.

- [ ] **Step 4: Review and push**

Request code review for the MVP-4 diff. Fix Critical/Important findings, rerun verification, commit, and push:

```bash
git push origin mvp1-topic-refinement
```
