"""Interactive onboarding research advisor.

Uses Gemini Pro with AFC (Automatic Function Calling) to guide new grad students
through setting up their personalized paper tracking configuration.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types

from src.config import LLMConfig
from src.llm.gemini_client import GeminiClient
from src.onboard.prompts import (
    INITIAL_MESSAGE,
    REFINE_CONTEXT_TEMPLATE,
    REFINE_MESSAGE,
    SYSTEM_PROMPT,
)
from src.onboard.tools import OnboardTools

logger = logging.getLogger(__name__)


class ResearchAdvisor:
    """Interactive research advisor using Gemini Pro + AFC.

    Conducts a multi-turn conversation with the user, automatically calling
    tool functions (search ArXiv, read papers, etc.) to help build a
    personalized research profile.
    """

    def __init__(
        self,
        llm_config: LLMConfig,
        config_path: str = "config.yaml",
        pdf_dir: Path = Path("data/pdfs"),
        sota_dir: Path = Path("data/sota"),
        existing_profile: Optional[dict] = None,
    ):
        self.llm_config = llm_config
        self.config_path = config_path
        self.existing_profile = existing_profile

        # Create the raw genai client for chat (separate from GeminiClient wrapper)
        self._genai_client = genai.Client(api_key=llm_config.api_key)

        # Create the GeminiClient wrapper for tools that need async LLM calls
        self._llm = GeminiClient(llm_config)

        # Initialize tools
        self._tools = OnboardTools(
            llm=self._llm,
            llm_config=llm_config,
            pdf_dir=pdf_dir,
            config_path=config_path,
            sota_dir=sota_dir,
        )

        # Build system prompt
        system_prompt = SYSTEM_PROMPT
        if existing_profile:
            topics_summary = "\n".join(
                f"  - {t['name']}: {t.get('query', 'N/A')}"
                for t in existing_profile.get("topics", [])
            )
            system_prompt += REFINE_CONTEXT_TEMPLATE.format(
                research_profile=existing_profile.get("research_profile", "Not set"),
                topics_summary=topics_summary or "  (none)",
                threshold=existing_profile.get("relevance_threshold", 6),
            )

        # Create chat session with AFC tools
        self._chat = self._genai_client.chats.create(
            model=llm_config.reader_model,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=[
                    self._tools.search_arxiv,
                    self._tools.fetch_paper,
                    self._tools.read_paper_experiments,
                    self._tools.save_onboard_result,
                ],
                temperature=0.7,  # More conversational than analysis
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=False,
                ),
            ),
        )

        self._done = False

    def run(self):
        """Run the interactive onboarding conversation loop."""
        # Send initial message to trigger Gemini's first question
        initial_msg = REFINE_MESSAGE if self.existing_profile else INITIAL_MESSAGE

        print("\n" + "=" * 60)
        print("  Research Paper Tracker - Interactive Setup")
        print("=" * 60)
        print("  Type your responses below. Type 'quit' or 'exit' to stop.")
        print("=" * 60 + "\n")

        try:
            response = self._chat.send_message(initial_msg)
            self._print_response(response)

            while not self._done:
                try:
                    user_input = input("\n> ").strip()
                except EOFError:
                    break

                if not user_input:
                    continue
                if user_input.lower() in ("quit", "exit", "q"):
                    print("\nExiting onboarding. Your progress has not been saved.")
                    break

                try:
                    response = self._chat.send_message(user_input)
                    self._print_response(response)
                except Exception as e:
                    logger.error(f"Error during conversation: {e}")
                    print(f"\n[Error: {e}. Please try again.]")

        except KeyboardInterrupt:
            print("\n\nInterrupted. Exiting onboarding.")

    def _print_response(self, response):
        """Print the model's response, handling tool call results."""
        if response.text:
            print(f"\n{response.text}")

        # Check if save_onboard_result was called (conversation complete)
        if response.automatic_function_calling_history:
            for item in response.automatic_function_calling_history:
                # Check function call parts
                if hasattr(item, 'parts'):
                    for part in item.parts:
                        if hasattr(part, 'function_call') and part.function_call:
                            fc = part.function_call
                            if fc.name == "save_onboard_result":
                                self._done = True
                            elif fc.name == "search_arxiv":
                                args = dict(fc.args) if fc.args else {}
                                q = args.get("query", "")
                                print(f"\n  [Searching ArXiv: {q}...]")
                            elif fc.name == "read_paper_experiments":
                                args = dict(fc.args) if fc.args else {}
                                aid = args.get("arxiv_id", "")
                                print(f"\n  [Deep-reading paper {aid}...]")
                            elif fc.name == "fetch_paper":
                                args = dict(fc.args) if fc.args else {}
                                aid = args.get("arxiv_id", "")
                                print(f"\n  [Fetching paper {aid}...]")
