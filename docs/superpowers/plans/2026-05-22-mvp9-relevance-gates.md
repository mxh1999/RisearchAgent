# MVP-9 Relevance Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build pre-download and post-reading relevance gates that prevent noisy discovery results from being downloaded or included in topic survey/SOTA artifacts.

**Architecture:** Add `src/survey/relevance.py` as the shared service for decision parsing, prompts, discovery screening, reading validation, and validation report loading. Add `src/survey/relevance_cli.py` for `topic screen` and `topic validate`, then wire both commands through the existing topic command router.

**Tech Stack:** Python dataclasses, pathlib, json, PyYAML, pytest, existing Gemini JSON API protocol, existing topic/discovery/reading models.

---

## File Structure

- Create `src/survey/relevance.py`
  - `RelevanceDecision`, `ScreeningReport`, `ValidationReport`
  - `screen_discovery_candidates(...)`
  - `validate_reading_packages(...)`
  - `load_validation_inclusions(...)`
- Create `src/survey/relevance_cli.py`
  - `cmd_topic_screen(args, llm=None)`
  - `cmd_topic_validate(args, llm=None)`
- Modify `src/survey/topic_update.py`
  - filter loaded packages when `state/relevance_validations.json` exists.
- Modify `src/survey/topic_cli.py`
  - dispatch `topic screen` and `topic validate`.
- Modify `run.py`
  - parse new subcommands and validate threshold/limit.
- Create `tests/survey/test_relevance_gates.py`
  - service, CLI, parser, and update-filter tests.

---

### Task 1: Shared Relevance Service

**Files:**
- Create: `tests/survey/test_relevance_gates.py`
- Create: `src/survey/relevance.py`

- [ ] **Step 1: Write failing tests**

Write tests for fake LLM decisions that accept one discovery candidate, reject one obvious false positive, write `screening_report.json`, update `discovery_candidates.json`, and render `ingest_manifest.draft.yaml` with accepted candidates only.

- [ ] **Step 2: Verify RED**

Run:

```bash
python -m pytest tests/survey/test_relevance_gates.py -q
```

Expected: import failure for `src.survey.relevance`.

- [ ] **Step 3: Implement service**

Implement dataclasses, decision parsing, prompt builders, discovery JSON mutation, markdown/draft manifest refresh, and report writing.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
python -m pytest tests/survey/test_relevance_gates.py -q
```

Expected: relevance service tests pass.

---

### Task 2: Post-Reading Validation And Topic Update Filtering

**Files:**
- Modify: `tests/survey/test_relevance_gates.py`
- Modify: `src/survey/relevance.py`
- Modify: `src/survey/topic_update.py`

- [ ] **Step 1: Write failing validation tests**

Add tests that write two reading packages, validate them with a fake LLM, write `state/relevance_validations.json`, and assert `load_topic_update_context(...)` excludes the rejected package.

- [ ] **Step 2: Verify RED**

Run:

```bash
python -m pytest tests/survey/test_relevance_gates.py::test_topic_update_context_filters_rejected_validation -q
```

Expected: rejected package is still loaded because filtering is not implemented.

- [ ] **Step 3: Implement validation and filtering**

Add reading-package validation service and make `load_topic_update_context(...)` apply validation includes when the report exists.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
python -m pytest tests/survey/test_relevance_gates.py tests/survey/test_topic_update.py -q
```

Expected: relevance and topic update tests pass.

---

### Task 3: CLI Wiring

**Files:**
- Modify: `tests/survey/test_relevance_gates.py`
- Create: `src/survey/relevance_cli.py`
- Modify: `src/survey/topic_cli.py`
- Modify: `run.py`

- [ ] **Step 1: Write failing CLI/parser tests**

Add parser tests for:

```bash
python run.py topic screen --topic data/topics/utility_nav/topic.yaml --threshold 0.7 --limit 3 --dry-run
python run.py topic validate --topic data/topics/utility_nav/topic.yaml --readings-dir papers --threshold 0.7
```

Also test invalid thresholds and non-positive limits.

- [ ] **Step 2: Verify RED**

Run:

```bash
python -m pytest tests/survey/test_relevance_gates.py -q
```

Expected: parser rejects unknown commands.

- [ ] **Step 3: Implement CLI and parser wiring**

Add command functions that build Gemini with the filter model by default, call the services, and print concise report paths/counts.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
python -m pytest tests/survey/test_relevance_gates.py -q
```

Expected: all relevance gate tests pass.

---

### Task 4: Final Verification

**Files:**
- All changed files.

- [ ] **Step 1: Run focused tests**

```bash
python -m pytest tests/survey/test_relevance_gates.py tests/survey/test_topic_discover.py tests/survey/test_topic_download.py tests/survey/test_topic_update.py -q
```

- [ ] **Step 2: Run full tests and compile**

```bash
python -m pytest -q
python -m compileall src run.py
git diff --check
```

- [ ] **Step 3: Optional real smoke**

Run `topic screen` and `topic validate` against the existing ignored E2E topic only if API quota is acceptable.

---

## Self-Review

- Spec coverage: pre-download screening, post-reading validation, reports, CLI, and update filtering are covered.
- Placeholder scan: no open TODO/TBD items.
- Type consistency: command and service names match planned imports.

