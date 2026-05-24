import pytest

from src.reader.staged_models import PageText
from src.reader.staged_reader import StagedPaperReader


class NumericStringExperimentLLM:
    async def generate_json(self, prompt, model=None, temperature=None):
        if "summary" in prompt.split("## Stage", 1)[1].splitlines()[1]:
            return {
                "summary": {
                    "problem": "Agents need object memory.",
                    "method": "Store object locations in memory.",
                    "takeaway": "Object memory helps navigation.",
                    "contributions": ["Object memory map"],
                }
            }
        if "section_notes" in prompt.split("## Stage", 1)[1].splitlines()[1]:
            return {"claims": [], "critique": [], "follow_up_questions": []}
        if "method" in prompt.split("## Stage", 1)[1].splitlines()[1]:
            return {"method_modules": []}
        if "experiments" in prompt.split("## Stage", 1)[1].splitlines()[1]:
            return {
                "experiments": [
                    {
                        "benchmark": "ObjectNav-Smoke",
                        "setting": "synthetic validation",
                        "metric": "success_rate",
                        "method": "ObjectMemoryMap",
                        "value": "0.75",
                        "higher_is_better": True,
                        "result_kind": "main_task",
                        "source": {
                            "text": "synthetic",
                            "page": 1,
                            "section": "Experiments",
                            "quote": "success_rate 0.75",
                            "confidence": "low",
                        },
                    }
                ]
            }
        if "topic_relation" in prompt.split("## Stage", 1)[1].splitlines()[1]:
            return {
                "topic_relation": {
                    "relevance": "core",
                    "concept_axes": [],
                    "collision_risk": "low",
                    "differentiation": "",
                }
            }
        raise AssertionError("Unknown stage")


@pytest.mark.asyncio
async def test_staged_reader_accepts_numeric_string_experiment_values() -> None:
    reader = StagedPaperReader(NumericStringExperimentLLM(), model="fake-model")

    package = await reader.read(
        paper_id="smoke-read",
        title="Object Memory Maps for Embodied Navigation",
        source_path="synthetic.txt",
        pages=[
            PageText(
                page=1,
                text="ObjectMemoryMap reaches success_rate 0.75.",
                char_start=0,
                char_end=43,
            )
        ],
    )

    assert package.experiments[0].value == 0.75
