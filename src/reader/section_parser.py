import json
import logging
import re
from typing import Optional

from src.config import LLMConfig
from src.llm.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

# Standard section names that the LLM should map to
STANDARD_SECTIONS = [
    "abstract", "introduction", "related_work", "background",
    "method", "experiments", "discussion", "conclusion",
    "limitations", "references", "appendix",
]

SECTION_PARSE_PROMPT = """You are an expert at parsing academic paper structure.

Below is the full text of an academic paper. Each line is prefixed with its line number.

Your task: identify the major sections of this paper and output their line ranges.

Map each section to one of these standard names:
{standard_sections}

If a section doesn't fit any standard name, use the closest match. For example:
- "Our Approach" / "Proposed Framework" / "Architecture" → "method"
- "Evaluation" / "Results" / "Empirical Study" → "experiments"
- "Prior Work" / "Literature Review" → "related_work"
- "Future Work" → "limitations"

Output a JSON array of objects, sorted by start_line:
[
  {{"name": "abstract", "start_line": 1, "end_line": 15}},
  {{"name": "introduction", "start_line": 16, "end_line": 45}},
  ...
]

Rules:
- Every line of the paper should belong to exactly one section (no gaps, no overlaps)
- The first section starts at line 1
- The last section ends at the last line
- If the paper starts with content before any heading, call it "abstract" or "introduction" as appropriate
- Do NOT include the section heading line itself in the previous section — it belongs to the new section
- "references" section (bibliography) should be identified if present

Paper text:
{numbered_text}"""


class LLMSectionParser:
    """Parse paper sections using LLM to identify section boundaries."""

    def __init__(self, llm: GeminiClient, config: LLMConfig):
        self.llm = llm
        self.config = config

    async def parse_sections(self, full_text: str) -> dict[str, str]:
        """Use Flash model to identify paper section structure.

        Returns a dict mapping section names to their text content.
        Always includes 'full_text' key.
        Falls back to regex parsing if LLM call fails.
        """
        sections: dict[str, str] = {"full_text": full_text}

        try:
            result = await self._llm_parse(full_text)
            sections.update(result)
            parsed_count = len(sections) - 1
            logger.info(f"LLM parsed {parsed_count} sections: {list(sections.keys())}")
        except Exception as e:
            logger.warning(f"LLM section parsing failed ({e}), falling back to regex")
            result = _regex_fallback(full_text)
            sections.update(result)
            parsed_count = len(sections) - 1
            logger.info(f"Regex parsed {parsed_count} sections: {list(sections.keys())}")

        return sections

    async def _llm_parse(self, full_text: str) -> dict[str, str]:
        """Call Flash model to identify section boundaries."""
        lines = full_text.split("\n")
        total_lines = len(lines)

        # Add line number prefixes
        numbered_lines = [f"{i + 1:>5}| {line}" for i, line in enumerate(lines)]
        numbered_text = "\n".join(numbered_lines)

        prompt = SECTION_PARSE_PROMPT.format(
            standard_sections=", ".join(STANDARD_SECTIONS),
            numbered_text=numbered_text,
        )

        raw = await self.llm.generate_json(
            prompt,
            model=self.config.filter_model,  # Flash model
            temperature=0.0,
        )

        # Parse the section boundaries
        if not isinstance(raw, list) or not raw:
            raise ValueError(f"Expected a non-empty list, got: {type(raw)}")

        sections: dict[str, str] = {}
        for entry in raw:
            name = entry.get("name", "").lower().strip()
            start = entry.get("start_line", 1)
            end = entry.get("end_line", total_lines)

            # Validate
            if not name or name not in STANDARD_SECTIONS:
                logger.debug(f"Skipping unknown section name: {name}")
                continue

            # Convert to 0-indexed and clamp
            start_idx = max(0, start - 1)
            end_idx = min(total_lines, end)

            text = "\n".join(lines[start_idx:end_idx]).strip()
            if text:
                # If section name already exists, append
                if name in sections:
                    sections[name] = sections[name] + "\n\n" + text
                else:
                    sections[name] = text

        if not sections:
            raise ValueError("LLM returned no valid sections")

        return sections


# --- Regex fallback (legacy) ---

_SECTION_PATTERNS = [
    (r"(?i)^(?:\d+\.?\s*)?introduction", "introduction"),
    (r"(?i)^(?:\d+\.?\s*)?related\s+work", "related_work"),
    (r"(?i)^(?:\d+\.?\s*)?background", "background"),
    (r"(?i)^(?:\d+\.?\s*)?(?:method|approach|proposed\s+method|methodology|our\s+approach)", "method"),
    (r"(?i)^(?:\d+\.?\s*)?(?:experiment|evaluation|results|empirical)", "experiments"),
    (r"(?i)^(?:\d+\.?\s*)?(?:discussion)", "discussion"),
    (r"(?i)^(?:\d+\.?\s*)?(?:conclusion|concluding)", "conclusion"),
    (r"(?i)^(?:\d+\.?\s*)?(?:abstract)", "abstract"),
    (r"(?i)^(?:\d+\.?\s*)?(?:limitation|future\s+work)", "limitations"),
]


def _regex_fallback(full_text: str) -> dict[str, str]:
    """Parse paper sections using regex pattern matching (legacy fallback)."""
    lines = full_text.split("\n")
    current_section = "preamble"
    section_lines: dict[str, list[str]] = {"preamble": []}

    for line in lines:
        stripped = line.strip()
        if not stripped:
            section_lines.setdefault(current_section, []).append(line)
            continue

        for pattern, name in _SECTION_PATTERNS:
            if re.match(pattern, stripped):
                current_section = name
                section_lines.setdefault(current_section, [])
                break

        section_lines.setdefault(current_section, []).append(line)

    result: dict[str, str] = {}
    for name, lines_list in section_lines.items():
        text = "\n".join(lines_list).strip()
        if text:
            result[name] = text

    return result


def get_section_for_pass(sections: dict[str, str], pass_name: str) -> str:
    """Get relevant text for each reading pass.

    Pass 1 (method_intro): introduction + method
    Pass 2 (experiments): experiments
    Pass 3 (context): related_work + conclusion + limitations
    """
    if pass_name == "method_intro":
        parts = []
        for key in ["introduction", "method", "background"]:
            if key in sections:
                parts.append(sections[key])
        return "\n\n".join(parts) if parts else sections["full_text"][:15000]

    elif pass_name == "experiments":
        parts = []
        for key in ["experiments", "discussion"]:
            if key in sections:
                parts.append(sections[key])
        text = "\n\n".join(parts) if parts else ""
        # If the extracted experiment section is too short (< 3000 chars),
        # it likely missed table data due to PDF parsing issues.
        # Fall back to the latter portion of full_text which typically
        # contains experiments and results.
        if len(text) < 3000:
            full = sections["full_text"]
            text = full[len(full) // 3:]
        return text

    elif pass_name == "context":
        parts = []
        for key in ["related_work", "conclusion", "limitations"]:
            if key in sections:
                parts.append(sections[key])
        return "\n\n".join(parts) if parts else sections["full_text"][-10000:]

    return sections["full_text"]
