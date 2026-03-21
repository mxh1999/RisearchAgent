import logging
from typing import Optional

from src.config import LLMConfig
from src.llm.gemini_client import GeminiClient
from src.models import BenchmarkResult, DeepReading
from src.reader.section_parser import get_section_for_pass, parse_sections

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

PASS2_PROMPT = """You are a senior research scientist performing a deep reading of an academic paper.

## Task: Analyze the Experiments and Results sections

Paper title: {title}

Text:
{text}

Respond in JSON:
{{
    "experimental_setup": "<Datasets, environments, baselines, metrics used. 2-4 sentences>",
    "main_results": "<Key quantitative findings and comparisons. 3-5 sentences>",
    "extracted_benchmarks": [
        {{
            "benchmark_name": "<name>",
            "metric_name": "<metric>",
            "value": <float>,
            "unit": "<unit like % or score>",
            "is_sota": <true/false>
        }}
    ]
}}

For extracted_benchmarks, only include results that are clearly reported as the paper's own method's performance.
If no clear benchmark results are found, return an empty list."""

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

    async def read_paper(
        self, arxiv_id: str, title: str, full_text: str
    ) -> Optional[DeepReading]:
        """Perform three-pass deep reading of a paper."""
        try:
            sections = parse_sections(full_text)

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

            benchmarks = [
                BenchmarkResult(
                    benchmark_name=b["benchmark_name"],
                    metric_name=b["metric_name"],
                    value=float(b["value"]),
                    unit=b.get("unit", ""),
                    is_sota=b.get("is_sota", False),
                )
                for b in pass2.get("extracted_benchmarks", [])
            ]

            return DeepReading(
                arxiv_id=arxiv_id,
                problem_statement=pass1["problem_statement"],
                proposed_method=pass1["proposed_method"],
                key_contributions=pass1.get("key_contributions", []),
                experimental_setup=pass2["experimental_setup"],
                main_results=pass2["main_results"],
                limitations=pass3["limitations"],
                comparison_to_prior_work=pass3["comparison_to_prior_work"],
                extracted_benchmarks=benchmarks,
            )

        except Exception as e:
            logger.error(f"Deep reading failed for {arxiv_id}: {e}")
            return None
