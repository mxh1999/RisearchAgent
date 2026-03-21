import logging
from typing import Optional

from src.config import LLMConfig
from src.llm.gemini_client import GeminiClient
from src.models import DeepReading, ExperimentEntry, ExperimentTable, MethodResult
from src.reader.section_parser import LLMSectionParser, get_section_for_pass

logger = logging.getLogger(__name__)

PASS1_PROMPT = """You are a senior research scientist performing a deep reading of an academic paper.

## Task: Analyze the Introduction and Method sections

Paper title: {title}

Text:
{text}

Respond in JSON:
{{
    "problem_statement": "<What problem does the paper address? 2-3 sentences>",
    "proposed_method": "<Detailed description of the proposed method/approach. 3-5 sentences>",
    "key_contributions": ["<contribution 1>", "<contribution 2>", ...]
}}"""

PASS2_PROMPT = """You are a senior research scientist extracting experimental results from an academic paper.

## Task: Extract ALL quantitative results from the Experiments and Results sections

Paper title: {title}

Text:
{text}

You must extract TWO layers of information:

### Layer 1: Structured results (entries)
Extract ALL methods (both the paper's proposed method AND baselines) with their scores on each benchmark+setting+metric combination.

### Layer 2: Detailed experiment description (details)
A thorough free-text description covering:
- Training data and pretrained models used
- Evaluation split and number of episodes/samples
- Special settings (zero-shot vs trained, oracle stop vs learned stop, etc.)
- How baselines were obtained (official numbers vs reproduced)
- Any discussion of data discrepancies or differences in evaluation protocol

Respond in JSON:
{{
    "experimental_setup": "<Brief overview of experimental setup. 2-4 sentences>",
    "main_results": "<Key quantitative findings and comparisons. 3-5 sentences>",
    "entries": [
        {{
            "benchmark": "<benchmark name, e.g. HM3D ObjectNav>",
            "setting": "<specific setting, e.g. zero-shot val unseen>",
            "metric": "<metric name, e.g. SR, SPL, mAP>",
            "higher_is_better": true,
            "results": [
                {{"method": "<method name>", "value": <float>, "is_paper_method": true}},
                {{"method": "<baseline name>", "value": <float>, "is_paper_method": false}}
            ]
        }}
    ],
    "details": "<Detailed experiment description as described above. Be thorough.>"
}}

Guidelines:
- Include ALL methods from comparison tables, not just the paper's own method
- Each unique (benchmark, setting, metric) combination should be a separate entry
- Set higher_is_better=false for error metrics, loss, collision rate, etc.
- If the setting is not clearly specified, use "default"
- If no clear benchmark results are found, return an empty entries list"""

PASS3_PROMPT = """You are a senior research scientist performing a deep reading of an academic paper.

## Task: Analyze the Related Work, Conclusion, and Limitations

Paper title: {title}

Text:
{text}

Respond in JSON:
{{
    "comparison_to_prior_work": "<How does this work position itself relative to prior work? 2-4 sentences>",
    "limitations": "<Acknowledged or apparent limitations. 2-3 sentences>"
}}"""


class DeepReader:
    def __init__(self, llm: GeminiClient, config: LLMConfig):
        self.llm = llm
        self.config = config
        self.section_parser = LLMSectionParser(llm, config)

    async def read_paper(
        self, arxiv_id: str, title: str, full_text: str
    ) -> Optional[DeepReading]:
        """Perform three-pass deep reading of a paper."""
        try:
            sections = await self.section_parser.parse_sections(full_text)

            # Pass 1: Method + Introduction
            text1 = get_section_for_pass(sections, "method_intro")
            pass1 = await self.llm.generate_json(
                PASS1_PROMPT.format(title=title, text=text1[:30000]),
                model=self.config.reader_model,
            )

            # Pass 2: Experiments
            text2 = get_section_for_pass(sections, "experiments")
            pass2 = await self.llm.generate_json(
                PASS2_PROMPT.format(title=title, text=text2[:30000]),
                model=self.config.reader_model,
            )

            # Pass 3: Context
            text3 = get_section_for_pass(sections, "context")
            pass3 = await self.llm.generate_json(
                PASS3_PROMPT.format(title=title, text=text3[:30000]),
                model=self.config.reader_model,
            )

            # Build ExperimentTable from Pass 2
            experiment_table = self._parse_experiment_table(
                arxiv_id, pass2
            )

            return DeepReading(
                arxiv_id=arxiv_id,
                problem_statement=pass1["problem_statement"],
                proposed_method=pass1["proposed_method"],
                key_contributions=pass1.get("key_contributions", []),
                experimental_setup=pass2["experimental_setup"],
                main_results=pass2["main_results"],
                limitations=pass3["limitations"],
                comparison_to_prior_work=pass3["comparison_to_prior_work"],
                experiment_table=experiment_table,
            )

        except Exception as e:
            logger.error(f"Deep reading failed for {arxiv_id}: {e}")
            return None

    def _parse_experiment_table(
        self, arxiv_id: str, pass2: dict
    ) -> Optional[ExperimentTable]:
        """Parse Pass 2 JSON into ExperimentTable."""
        raw_entries = pass2.get("entries", [])
        if not raw_entries:
            return None

        entries = []
        for raw in raw_entries:
            results = []
            for r in raw.get("results", []):
                try:
                    value = float(r["value"])
                except (TypeError, ValueError, KeyError):
                    logger.warning(f"Skipping result with invalid value: {r}")
                    continue
                results.append(MethodResult(
                    method_name=r.get("method", "unknown"),
                    value=value,
                    is_paper_method=r.get("is_paper_method", False),
                ))
            entries.append(
                ExperimentEntry(
                    benchmark=raw["benchmark"],
                    setting=raw.get("setting", "default"),
                    metric=raw["metric"],
                    higher_is_better=raw.get("higher_is_better", True),
                    results=results,
                )
            )

        return ExperimentTable(
            arxiv_id=arxiv_id,
            entries=entries,
            details=pass2.get("details", ""),
        )
