# MVP-8 Topic Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `python run.py topic download --topic ...`, a deterministic workflow that turns topic discovery candidates into local PDFs and a valid MVP-6 ingestion manifest.

**Architecture:** Add `src/survey/topic_download.py` as the pure workflow layer for loading discovery artifacts, filtering candidates, downloading PDFs, writing manifests, and writing reports. Add `src/survey/download_cli.py` for CLI preflight and console output, then dispatch through the existing topic command router.

**Tech Stack:** Python dataclasses, pathlib, json, PyYAML, aiohttp, pytest, existing topic loading and ingest manifest validation helpers.

---

## File Structure

- Create `src/survey/topic_download.py`
  - `DownloadCandidate`, `DownloadOutcome`, `DownloadReport`
  - `load_download_candidates(...)`
  - `materialize_topic_downloads(...)`
  - `write_ingest_manifest(...)`
- Create `src/survey/download_cli.py`
  - `cmd_topic_download(args, download_one=None)`
- Modify `src/survey/topic_cli.py`
  - dispatch `topic download`
- Modify `run.py`
  - parse `topic download` arguments and validate `--limit` / `--all`
- Create `tests/survey/test_topic_download.py`
  - service, report, manifest, CLI, parser tests

---

### Task 1: Download Service Tests And Models

**Files:**
- Create: `tests/survey/test_topic_download.py`
- Create: `src/survey/topic_download.py`

- [ ] **Step 1: Write failing tests for filtering, download, report, and manifest**

Add tests that create a temporary topic directory, a discovery JSON file, and a fake async downloader. Assert that `materialize_topic_downloads(...)` downloads candidate rows, skips existing staged papers, writes `pdfs/<paper_id>.pdf`, writes `ingest_manifest.yaml`, and writes `state/download_report.json`.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python -m pytest tests/survey/test_topic_download.py -q
```

Expected: import or symbol failures because `topic_download.py` does not exist.

- [ ] **Step 3: Implement minimal service layer**

Create `src/survey/topic_download.py` with dataclasses, discovery loading, candidate filtering, atomic PDF download using an injectable downloader, manifest writing, and JSON report writing.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```bash
python -m pytest tests/survey/test_topic_download.py -q
```

Expected: topic download service tests pass.

---

### Task 2: CLI Wiring

**Files:**
- Modify: `tests/survey/test_topic_download.py`
- Create: `src/survey/download_cli.py`
- Modify: `src/survey/topic_cli.py`
- Modify: `run.py`

- [ ] **Step 1: Write failing CLI and parser tests**

Add tests that verify parser support for:

```bash
topic download --topic data/topics/utility_nav/topic.yaml
topic download --topic data/topics/utility_nav/topic.yaml --all
topic download --topic data/topics/utility_nav/topic.yaml --limit 3 --include-existing --force
```

Also test that `--all --limit 3` and non-positive limits fail parser validation.

- [ ] **Step 2: Run CLI tests and verify RED**

Run:

```bash
python -m pytest tests/survey/test_topic_download.py -q
```

Expected: parser and dispatch failures because `topic download` is not wired.

- [ ] **Step 3: Implement CLI and parser wiring**

Add `src/survey/download_cli.py`, route `args.topic_command == "download"` in `src/survey/topic_cli.py`, and add the parser block in `run.py`.

- [ ] **Step 4: Run CLI tests and verify GREEN**

Run:

```bash
python -m pytest tests/survey/test_topic_download.py -q
```

Expected: topic download service and CLI tests pass.

---

### Task 3: Integration Verification

**Files:**
- Modify: `tests/survey/test_topic_download.py`

- [ ] **Step 1: Add manifest compatibility test**

Add a test that runs `materialize_topic_downloads(...)`, then loads the generated `ingest_manifest.yaml` with `src.survey.topic_ingest.load_ingest_manifest` and asserts the resulting entry has the expected `paper_id`, `title`, and resolved PDF path.

- [ ] **Step 2: Run focused compatibility test and verify RED/GREEN**

Run:

```bash
python -m pytest tests/survey/test_topic_download.py -q
```

Expected: all topic download tests pass after any manifest shape fix.

- [ ] **Step 3: Run full verification**

Run:

```bash
python -m pytest -q
python -m compileall src run.py
```

Expected: all tests pass and compileall exits 0.

---

## Self-Review

- Spec coverage: service, CLI, manifest output, report output, failure isolation, and MVP-6 compatibility are covered.
- Placeholder scan: no open TODO/TBD items.
- Type consistency: service names match planned imports and CLI names.

