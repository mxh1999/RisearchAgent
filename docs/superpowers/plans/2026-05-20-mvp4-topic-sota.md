# MVP-4 Topic SOTA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a topic-scoped SOTA updater that converts staged reading package experiment records into `sota.md` and `state/sota_records.jsonl`.

**Architecture:** Add a small offline SOTA module under `src/survey/` because MVP-4 operates on survey topic artifacts rather than the older global SOTA tracker. The module loads reading packages through the existing loader, normalizes experiment records, renders deterministic markdown, and writes stable topic artifacts without touching `topic.yaml`.

**Tech Stack:** Python dataclasses, existing `PaperReadingPackage` / `ExperimentRecord`, existing `TopicArtifactManager.update_auto_block`, pytest.

---

## File Structure

- Create `src/survey/sota_models.py`: topic SOTA record dataclass, grouping key helpers, and conversion from reading packages.
- Create `src/survey/sota_renderer.py`: render grouped SOTA records into markdown tables.
- Create `src/survey/sota_cli.py`: command handler for `python run.py sota update --topic ...`.
- Modify `src/survey/artifacts.py`: ensure `sota.md` exists without rewriting `topic.yaml`.
- Modify `run.py`: add `sota update` subcommand while preserving the old `python run.py sota` behavior.
- Test `tests/survey/test_sota_models.py`: normalization, conversion, JSONL.
- Test `tests/survey/test_sota_renderer.py`: sorted markdown and warning rendering.
- Test `tests/survey/test_sota_cli.py`: parser/workflow/path safety/topic preservation.

---

### Task 1: Topic SOTA Models

**Files:**
- Create: `src/survey/sota_models.py`
- Test: `tests/survey/test_sota_models.py`

- [ ] **Step 1: Write failing tests**

Create tests that build two reading packages with experiment records and assert:

- whitespace normalization;
- empty setting becomes `N/A`;
- records are sorted by benchmark, setting, metric, value direction, method, paper id;
- JSONL round-trip preserves source evidence fields.

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest tests/survey/test_sota_models.py -q
```

Expected: fail because `src.survey.sota_models` does not exist.

- [ ] **Step 3: Implement models**

Implement:

- `TopicSOTARecord`
- `collect_sota_records(packages: list[PaperReadingPackage]) -> list[TopicSOTARecord]`
- `sort_sota_records(records: list[TopicSOTARecord]) -> list[TopicSOTARecord]`
- `records_to_jsonl(records: list[TopicSOTARecord]) -> str`
- `records_from_jsonl(text: str) -> list[TopicSOTARecord]`

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

### Task 2: SOTA Markdown Renderer

**Files:**
- Create: `src/survey/sota_renderer.py`
- Test: `tests/survey/test_sota_renderer.py`

- [ ] **Step 1: Write failing tests**

Create tests asserting:

- one benchmark section;
- one table per `(setting, metric)`;
- higher-is-better tables sort descending;
- lower-is-better tables sort ascending;
- evidence includes page, section, and truncated quote;
- mixed `higher_is_better` values render a warning.

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest tests/survey/test_sota_renderer.py -q
```

Expected: fail because renderer does not exist.

- [ ] **Step 3: Implement renderer**

Implement:

- `render_sota_markdown(records: list[TopicSOTARecord]) -> str`

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

### Task 3: SOTA CLI Workflow

**Files:**
- Create: `src/survey/sota_cli.py`
- Modify: `src/survey/artifacts.py`
- Modify: `run.py`
- Test: `tests/survey/test_sota_cli.py`

- [ ] **Step 1: Write failing tests**

Create tests asserting:

- `build_parser().parse_args(["sota", "update", "--topic", "..."])` parses `sota_command == "update"`;
- `build_parser().parse_args(["sota"])` still parses old show mode;
- `cmd_sota_update(args)` writes `sota.md` and `state/sota_records.jsonl`;
- manual text around `AUTO:sota` is preserved;
- `topic.yaml` bytes are unchanged;
- mismatched `topic_id` fails before writes;
- packages with no experiments fail before writes.

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
- use `TopicArtifactManager.ensure_topic_artifacts(topic)` and a new `ensure_sota_artifact(topic)` helper.

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

### Task 4: Smoke and Final Verification

**Files:**
- No tracked files expected unless tests reveal a bug.

- [ ] **Step 1: Run real smoke**

Run:

```bash
python run.py sota update --topic data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/topic.yaml
```

Expected:

- prints `SOTA: ...\sota.md`
- prints `Records: ...\state\sota_records.jsonl`
- `topic.yaml` hash remains unchanged.

- [ ] **Step 2: Inspect generated artifacts**

Run:

```bash
Get-Content data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/sota.md -TotalCount 120
Get-Content data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/state/sota_records.jsonl -TotalCount 5
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
