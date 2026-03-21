import logging
import re
from pathlib import Path
from typing import Optional

from src.config import LLMConfig
from src.llm.gemini_client import GeminiClient
from src.models import (
    ExperimentEntry,
    ExperimentTable,
    SOTAConflict,
    SOTAUpdateAction,
    SOTAUpdateReport,
)

logger = logging.getLogger(__name__)

CONFLICT_ANALYSIS_PROMPT = """You are an expert ML researcher analyzing discrepancies in benchmark results.

## Conflicts Found
The following methods have different scores reported by different papers:

{conflicts_text}

## Experiment Details from Current Paper
{experiment_details}

## Existing SOTA Leaderboard
{existing_md}

## Task
For each conflict, determine the likely cause and recommend how to handle it.

Respond in JSON:
{{
    "analyses": [
        {{
            "method": "<method name>",
            "metric": "<metric name>",
            "cause": "<one of: setting_diff, reproduction_diff, citation_error, unknown>",
            "explanation": "<brief explanation of the discrepancy>",
            "recommendation": "<keep_both | prefer_existing | prefer_new>"
        }}
    ]
}}

Cause categories:
- setting_diff: Different evaluation settings (split version, episodes, preprocessing)
- reproduction_diff: One paper reproduced the method vs using official numbers
- citation_error: Likely incorrect citation of the baseline number
- unknown: Cannot determine the cause"""

UPDATE_MD_PROMPT = """You are updating a SOTA leaderboard markdown file for a benchmark.

## Current Markdown (may be empty for new benchmarks)
{existing_md}

## New Data to Incorporate
Benchmark: {benchmark}
Setting: {setting}
Paper: {arxiv_id} ({paper_title})

New results to add:
{new_results}

{conflict_section}

## Instructions
Generate the updated markdown file. Follow this format exactly:

# {{Benchmark Name}}

## {{Setting}}

| Rank | Method | {{Metric1}}{{arrow1}} | {{Metric2}}{{arrow2}} | Paper | Notes |
|------|--------|------|------|-------|-------|
| 1 | Best Method | 67.2 | 35.1 | 2603.01813 | Brief note |
| 2 | Second | 52.0 | 24.3 | 2312.xxxxx | Brief note |

Rules:
- Use up-arrow (↑) for higher-is-better metrics, down-arrow (↓) for lower-is-better
- Sort by the first metric in the appropriate direction
- Merge metrics for the same (benchmark, setting) into a single table where possible
- Add conflict notes as blockquotes (> ) below the table when there are discrepancies
- Keep existing notes and add new ones as needed
- If a method appears in multiple papers, keep the entry with the most recent/authoritative source
- Rank should reflect the sorted order

Return ONLY the markdown content, no code fences."""


class SOTAKnowledgeBase:
    """Markdown-based SOTA knowledge base with conflict detection."""

    def __init__(self, sota_dir: Path, llm: GeminiClient, llm_config: LLMConfig):
        self.sota_dir = sota_dir
        self.sota_dir.mkdir(parents=True, exist_ok=True)
        self.llm = llm
        self.llm_config = llm_config

    async def update_from_experiment(
        self,
        arxiv_id: str,
        paper_title: str,
        experiment: ExperimentTable,
    ) -> SOTAUpdateReport:
        """Process one paper's experiment results and update SOTA markdown files."""
        report = SOTAUpdateReport(arxiv_id=arxiv_id)

        # Group entries by benchmark+setting for merged tables
        grouped: dict[tuple[str, str], list[ExperimentEntry]] = {}
        for entry in experiment.entries:
            key = (entry.benchmark, entry.setting)
            grouped.setdefault(key, []).append(entry)

        for (benchmark, setting), entries in grouped.items():
            md_path = self._benchmark_path(benchmark)
            existing_md = self._read_md(md_path)

            # Step 1: Check for conflicts across all entries in this group
            all_conflicts = []
            for entry in entries:
                conflicts = self._check_conflicts(entry, existing_md)
                all_conflicts.extend(conflicts)

            # Step 2: Analyze conflicts if any
            conflict_analysis = None
            if all_conflicts:
                report.conflicts_found += len(all_conflicts)
                conflict_analysis = await self._analyze_conflicts(
                    all_conflicts, experiment.details, existing_md
                )
                report.conflicts_resolved += len(all_conflicts)

            # Step 3: Update markdown via LLM
            updated_md = await self._update_md(
                existing_md, entries, setting, arxiv_id, paper_title,
                conflict_analysis=conflict_analysis,
            )
            self._write_md(md_path, updated_md)

            # Record action
            action_type = "new_entry" if not existing_md else "updated"
            if all_conflicts:
                action_type = "conflict_resolved"

            methods = set()
            for entry in entries:
                for r in entry.results:
                    if r.is_paper_method:
                        methods.add(r.method_name)

            report.actions.append(SOTAUpdateAction(
                benchmark=benchmark,
                action=action_type,
                summary=f"{'|'.join(methods) or 'baselines'} on {benchmark} ({setting})",
            ))

            logger.info(
                f"SOTA [{action_type}] {benchmark}/{setting}: "
                f"{len(all_conflicts)} conflicts"
            )

        return report

    def _benchmark_path(self, benchmark: str) -> Path:
        """Convert benchmark name to filesystem path."""
        safe_name = re.sub(r'[^\w\s-]', '', benchmark.lower())
        safe_name = re.sub(r'[\s]+', '_', safe_name.strip())
        return self.sota_dir / f"{safe_name}.md"

    def _read_md(self, path: Path) -> str:
        """Read existing markdown file, return empty string if not exists."""
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def _write_md(self, path: Path, content: str) -> None:
        """Write markdown content to file."""
        path.write_text(content, encoding="utf-8")

    def _check_conflicts(
        self, entry: ExperimentEntry, existing_md: str
    ) -> list[SOTAConflict]:
        """Check for value conflicts between paper-reported baselines and existing data."""
        if not existing_md:
            return []

        conflicts = []
        # Only check baselines (is_paper_method=False) for conflicts
        for result in entry.results:
            if result.is_paper_method:
                continue

            # Search for this method in the existing markdown table
            existing_value = self._find_method_value(
                existing_md, result.method_name, entry.metric
            )
            if existing_value is None:
                continue

            # Check relative difference
            if existing_value == 0:
                continue
            rel_diff = abs(result.value - existing_value) / abs(existing_value)
            if rel_diff > 0.05:  # >5% relative difference
                # Find which paper reported the existing value
                existing_source = self._find_method_paper(
                    existing_md, result.method_name
                )
                conflicts.append(SOTAConflict(
                    method=result.method_name,
                    metric=entry.metric,
                    paper_value=result.value,
                    existing_value=existing_value,
                    paper_source=existing_source or "unknown",
                ))

        return conflicts

    def _find_method_value(
        self, md_content: str, method_name: str, metric_name: str
    ) -> Optional[float]:
        """Find a method's value for a given metric in the markdown table."""
        # Find table headers to locate the metric column
        for line in md_content.split("\n"):
            if "|" not in line or "Rank" not in line:
                continue

            headers = [h.strip() for h in line.split("|")]
            # Find metric column index (strip arrows)
            metric_col = None
            for i, h in enumerate(headers):
                clean_h = h.replace("↑", "").replace("↓", "").strip()
                if clean_h.lower() == metric_name.lower():
                    metric_col = i
                    break

            if metric_col is None:
                continue

            # Now search data rows for the method
            for data_line in md_content.split("\n"):
                if "|" not in data_line or "---" in data_line or "Rank" in data_line:
                    continue
                cells = [c.strip() for c in data_line.split("|")]
                if len(cells) <= metric_col:
                    continue

                # Check if method name matches (fuzzy)
                method_cell = cells[2] if len(cells) > 2 else ""
                if method_name.lower() in method_cell.lower() or method_cell.lower() in method_name.lower():
                    try:
                        return float(cells[metric_col])
                    except (ValueError, IndexError):
                        continue

        return None

    def _find_method_paper(self, md_content: str, method_name: str) -> Optional[str]:
        """Find the paper ID associated with a method in the markdown."""
        for line in md_content.split("\n"):
            if "|" not in line or "---" in line or "Rank" in line:
                continue
            cells = [c.strip() for c in line.split("|")]
            if len(cells) < 6:
                continue
            method_cell = cells[2] if len(cells) > 2 else ""
            if method_name.lower() in method_cell.lower() or method_cell.lower() in method_name.lower():
                # Paper ID is typically in the 5th column (index 5)
                paper_cell = cells[5] if len(cells) > 5 else ""
                paper_match = re.search(r'\d{4}\.\d{4,5}', paper_cell)
                if paper_match:
                    return paper_match.group()
        return None

    async def _analyze_conflicts(
        self,
        conflicts: list[SOTAConflict],
        experiment_details: str,
        existing_md: str,
    ) -> str:
        """Use LLM to analyze the cause of value conflicts."""
        conflicts_text = "\n".join(
            f"- {c.method} / {c.metric}: "
            f"current paper reports {c.paper_value}, "
            f"existing record shows {c.existing_value} (from paper {c.paper_source})"
            for c in conflicts
        )

        prompt = CONFLICT_ANALYSIS_PROMPT.format(
            conflicts_text=conflicts_text,
            experiment_details=experiment_details,
            existing_md=existing_md or "(No existing leaderboard)",
        )

        try:
            result = await self.llm.generate_json(
                prompt, model=self.llm_config.reader_model
            )
            # Format analyses into notes
            notes = []
            for a in result.get("analyses", []):
                notes.append(
                    f"> ⚠ {a['method']}/{a['metric']}: {a['explanation']} "
                    f"(cause: {a['cause']}, action: {a['recommendation']})"
                )
            return "\n".join(notes)
        except Exception as e:
            logger.error(f"Conflict analysis failed: {e}")
            return "\n".join(
                f"> ⚠ {c.method}/{c.metric}: paper reports {c.paper_value}, "
                f"existing shows {c.existing_value} (from {c.paper_source}). "
                f"Cause unknown."
                for c in conflicts
            )

    async def _update_md(
        self,
        existing_md: str,
        entries: list[ExperimentEntry],
        setting: str,
        arxiv_id: str,
        paper_title: str,
        conflict_analysis: Optional[str] = None,
    ) -> str:
        """Use LLM to generate updated markdown leaderboard."""
        # Format new results
        new_results_lines = []
        for entry in entries:
            for r in entry.results:
                tag = " [paper method]" if r.is_paper_method else ""
                arrow = "↑" if entry.higher_is_better else "↓"
                new_results_lines.append(
                    f"- {r.method_name}: {entry.metric}{arrow} = {r.value}{tag}"
                )
        new_results = "\n".join(new_results_lines)

        conflict_section = ""
        if conflict_analysis:
            conflict_section = (
                f"## Conflict Analysis\n"
                f"The following conflicts were detected and analyzed:\n"
                f"{conflict_analysis}\n"
                f"Incorporate these notes into the markdown."
            )

        benchmark_name = entries[0].benchmark if entries else "Unknown"

        prompt = UPDATE_MD_PROMPT.format(
            existing_md=existing_md or "(New benchmark, no existing data)",
            benchmark=benchmark_name,
            setting=setting,
            arxiv_id=arxiv_id,
            paper_title=paper_title,
            new_results=new_results,
            conflict_section=conflict_section,
        )

        try:
            result = await self.llm.generate(
                prompt, model=self.llm_config.reader_model
            )
            # Strip code fences if the LLM wrapped them
            result = result.strip()
            if result.startswith("```"):
                result = re.sub(r'^```\w*\n', '', result)
                result = re.sub(r'\n```$', '', result)
            return result.strip() + "\n"
        except Exception as e:
            logger.error(f"Markdown update generation failed: {e}")
            # Fallback: append raw data
            if existing_md:
                return existing_md + f"\n\n<!-- Raw data from {arxiv_id} -->\n{new_results}\n"
            return f"# {benchmark_name}\n\n## {setting}\n\n{new_results}\n"

    def get_all_benchmarks(self) -> list[tuple[str, str]]:
        """Return list of (filename, content) for all SOTA markdown files."""
        results = []
        if not self.sota_dir.exists():
            return results
        for md_file in sorted(self.sota_dir.glob("*.md")):
            content = md_file.read_text(encoding="utf-8")
            results.append((md_file.stem, content))
        return results
