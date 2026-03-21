import re
import logging

logger = logging.getLogger(__name__)

# Common section heading patterns in academic papers
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


def parse_sections(full_text: str) -> dict[str, str]:
    """Parse paper text into named sections.

    Returns a dict mapping section names to their text content.
    Always includes 'full_text' key. If parsing fails, only 'full_text' is returned.
    """
    sections: dict[str, str] = {"full_text": full_text}

    lines = full_text.split("\n")
    current_section = "preamble"
    section_lines: dict[str, list[str]] = {"preamble": []}

    for line in lines:
        stripped = line.strip()
        if not stripped:
            section_lines.setdefault(current_section, []).append(line)
            continue

        matched = False
        for pattern, name in _SECTION_PATTERNS:
            if re.match(pattern, stripped):
                current_section = name
                section_lines.setdefault(current_section, [])
                matched = True
                break

        section_lines.setdefault(current_section, []).append(line)

    for name, lines_list in section_lines.items():
        text = "\n".join(lines_list).strip()
        if text:
            sections[name] = text

    parsed_count = len(sections) - 1  # exclude full_text
    logger.info(f"Parsed {parsed_count} sections: {list(sections.keys())}")
    return sections


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
            # Use the second half of the paper (experiments are usually there)
            text = full[len(full) // 3:]
        return text

    elif pass_name == "context":
        parts = []
        for key in ["related_work", "conclusion", "limitations"]:
            if key in sections:
                parts.append(sections[key])
        return "\n\n".join(parts) if parts else sections["full_text"][-10000:]

    return sections["full_text"]
