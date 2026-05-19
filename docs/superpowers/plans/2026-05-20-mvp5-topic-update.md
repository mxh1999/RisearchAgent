# MVP-5 Topic Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `python run.py topic update --topic ...`, a single local workflow that refreshes survey artifacts, SOTA artifacts, and writes `state/topic_update_report.json`.

**Architecture:** Refactor existing survey and SOTA CLI modules to expose reusable service functions, then add a topic orchestration module that loads topic/readings once and calls those services. The orchestrator writes a small JSON report and preserves `topic.yaml` byte-for-byte.

**Tech Stack:** Python dataclasses, pathlib/json, existing `TopicProfile`, `PaperReadingPackage`, `TopicArtifactManager`, Gemini client protocol via existing modules, pytest.

---

## File Structure

- Modify `src/survey/cli.py`: add `synthesize_survey_artifacts(...)` service function and let `cmd_survey_synthesize` delegate to it.
- Modify `src/survey/sota_cli.py`: add `update_sota_artifacts(...)` service function and let `cmd_sota_update` delegate to it.
- Create `src/survey/topic_update.py`: topic update report models and orchestration.
- Modify `run.py`: add `topic update` parser and dispatch before global config loading.
- Test `tests/survey/test_topic_update.py`: report/preflight/orchestration behavior.
- Test `tests/survey/test_cli.py` and `tests/survey/test_sota_cli.py`: existing behavior still passes.

---

### Task 1: Extract Survey and SOTA Service Functions

**Files:**
- Modify: `src/survey/cli.py`
- Modify: `src/survey/sota_cli.py`
- Test: existing `tests/survey/test_cli.py`, `tests/survey/test_sota_cli.py`

- [ ] **Step 1: Write focused regression tests if needed**

The existing tests already call `cmd_survey_synthesize` and `cmd_sota_update`; preserve them. Add one assertion to each workflow test only if a service function return shape is required by later tasks.

- [ ] **Step 2: Refactor survey service**

Add a service function:

```python
async def synthesize_survey_artifacts(
    topic: TopicProfile,
    topic_dir: Path,
    packages: list[PaperReadingPackage],
    llm: SurveySynthesisLLM,
    model: str | None,
) -> dict[str, Path]:
    ...
```

It should update four AUTO blocks and append the `synthesize` event, then return paths for `survey`, `papers`, `positioning`, and `references`.

- [ ] **Step 3: Refactor SOTA service**

Add a service function:

```python
async def update_sota_artifacts(
    topic: TopicProfile,
    topic_dir: Path,
    packages: list[PaperReadingPackage],
    llm: SettingNormalizerLLM | None,
    model: str | None,
    use_llm: bool,
) -> dict[str, object]:
    ...
```

It should update `sota.md`, `state/sota_records.jsonl`, `state/sota_setting_groups.json`, append the `sota_update` event, and return paths plus `record_count` and `setting_group_count`.

- [ ] **Step 4: Run tests**

Run:

```bash
python -m pytest tests/survey/test_cli.py tests/survey/test_sota_cli.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/survey/cli.py src/survey/sota_cli.py tests/survey/test_cli.py tests/survey/test_sota_cli.py
git commit -m "refactor: expose survey and SOTA artifact services"
```

---

### Task 2: Topic Update Report and Preflight

**Files:**
- Create: `src/survey/topic_update.py`
- Test: `tests/survey/test_topic_update.py`

- [ ] **Step 1: Write failing tests**

Create tests for:

- `build_topic_update_report(...)` counts packages and experiments;
- report JSON includes `paper_ids`, `papers_with_experiments`, `papers_without_experiments`, and warnings;
- both skipped survey and skipped SOTA is rejected.

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest tests/survey/test_topic_update.py -q
```

Expected: fail because `src.survey.topic_update` does not exist.

- [ ] **Step 3: Implement report models**

Implement:

- `TopicUpdateStepReport`
- `TopicUpdateReport`
- `build_preflight_report(topic, readings_dir, packages) -> TopicUpdateReport`
- `write_topic_update_report(topic_dir, report) -> Path`

Use dataclasses with `to_dict()` methods.

- [ ] **Step 4: Run GREEN**

Run:

```bash
python -m pytest tests/survey/test_topic_update.py -q
```

Expected: report tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/survey/topic_update.py tests/survey/test_topic_update.py
git commit -m "feat: add topic update report"
```

---

### Task 3: Topic Update Orchestrator

**Files:**
- Modify: `src/survey/topic_update.py`
- Test: `tests/survey/test_topic_update.py`

- [ ] **Step 1: Write failing workflow tests**

Add tests for:

- update runs survey + SOTA with fake LLMs and writes report;
- `topic.yaml` bytes remain unchanged;
- manual text around survey and SOTA AUTO blocks remains;
- `skip_survey=True` does not create survey artifacts;
- `skip_sota=True` does not create SOTA artifacts.

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest tests/survey/test_topic_update.py -q
```

Expected: fail because orchestration function is not implemented.

- [ ] **Step 3: Implement orchestrator**

Implement:

```python
async def update_topic_artifacts(
    topic_path: Path,
    readings_dir: Path | None,
    survey_llm,
    survey_model: str | None,
    sota_llm,
    sota_model: str | None,
    skip_survey: bool,
    skip_sota: bool,
    use_sota_llm: bool,
) -> TopicUpdateReport:
    ...
```

Behavior:

- load topic via existing `_load_topic`;
- validate topic path via existing `_validate_topic_path`;
- load packages via `load_reading_packages`;
- reject both skips;
- call service functions based on flags;
- write report in a `finally` only after successful step updates are represented; for MVP-5, failed substeps can raise and skip report writing.

- [ ] **Step 4: Run GREEN**

Run:

```bash
python -m pytest tests/survey/test_topic_update.py -q
```

Expected: all topic update tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/survey/topic_update.py tests/survey/test_topic_update.py
git commit -m "feat: orchestrate topic artifact updates"
```

---

### Task 4: CLI Integration

**Files:**
- Modify: `run.py`
- Create: `src/survey/topic_cli.py`
- Test: `tests/survey/test_topic_update.py` or `tests/survey/test_topic_cli.py`

- [ ] **Step 1: Write failing parser/CLI tests**

Assert:

- `build_parser().parse_args(["topic", "update", "--topic", "data/topics/x/topic.yaml"])` parses correctly;
- both `--skip-survey` and `--skip-sota` are rejected or fail before writes;
- local topic/readings validation happens before Gemini/API key checks.

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest tests/survey/test_topic_update.py -q
```

Expected: fail because parser/CLI is missing.

- [ ] **Step 3: Implement CLI**

Create `src/survey/topic_cli.py`:

- `cmd_topic_update(args) -> None`
- build survey Gemini client unless `--skip-survey`;
- build SOTA Gemini client lazily only when SOTA needs LLM for unmatched settings;
- print report path and artifact statuses.

Modify `run.py`:

- add `topic` parser with `update` subcommand;
- dispatch before loading global config.

- [ ] **Step 4: Run GREEN**

Run:

```bash
python -m pytest tests/survey/test_topic_update.py tests/survey/test_cli.py tests/survey/test_sota_cli.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add run.py src/survey/topic_cli.py tests/survey/test_topic_update.py
git commit -m "feat: add topic update CLI"
```

---

### Task 5: Smoke, Review, Push

**Files:**
- No tracked files expected unless smoke finds bugs.

- [ ] **Step 1: Smoke with conservative SOTA**

Run:

```bash
python run.py topic update --topic data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/topic.yaml --no-llm-normalize
```

Expected:

- updates survey artifacts;
- updates SOTA artifacts;
- writes `state/topic_update_report.json`;
- `topic.yaml` hash unchanged.

- [ ] **Step 2: Inspect report**

Run:

```bash
Get-Content data/topics-smoke/task_driven_3d_utility_learning_for_embodied_navigation/state/topic_update_report.json -TotalCount 120
```

Expected: report has counts, warnings, survey status, and SOTA status.

- [ ] **Step 3: Full verification**

Run:

```bash
python -m pytest -q
python -m compileall src run.py
python -c "import src.survey.topic_update; import src.survey.topic_cli"
git status --short --branch
```

Expected: all tests pass, compile/import exit 0, tracked worktree clean.

- [ ] **Step 4: Review and push**

Request code review for MVP-5 diff. Fix Critical/Important findings, rerun verification, commit, and push:

```bash
git push origin mvp1-topic-refinement
```
