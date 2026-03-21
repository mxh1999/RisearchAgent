#!/usr/bin/env python3
"""RisearchAgent - CLI entry point."""

import argparse
import asyncio
import logging
import sys

from src.config import load_config
from src.pipeline.orchestrator import PipelineOrchestrator


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


async def cmd_crawl(config):
    """Stage 1: Crawl ArXiv papers."""
    orch = PipelineOrchestrator(config)
    await orch.db.initialize()
    count = await orch.stage_crawl()
    print(f"\nCrawled {count} papers.")
    stats = await orch.db.get_stats()
    print(f"Database: {stats['total_papers']} total papers")


async def cmd_filter(config):
    """Stage 2: Filter papers by relevance."""
    orch = PipelineOrchestrator(config)
    await orch.db.initialize()
    count = await orch.stage_filter()
    print(f"\nFiltered {count} papers.")
    stats = await orch.db.get_stats()
    print(f"Database: {stats['filtered']} papers scored")


async def cmd_read(config, arxiv_id: str):
    """Stage 3: Deep-read a specific paper."""
    orch = PipelineOrchestrator(config)
    result = await orch.read_single_paper(arxiv_id)

    if not result:
        print(f"Failed to read paper {arxiv_id}")
        sys.exit(1)

    reading = result["reading"]
    delta = result["contribution"]

    print(f"\n{'='*60}")
    print(f"Paper: {arxiv_id}")
    print(f"{'='*60}")
    print(f"\nProblem: {reading.problem_statement}")
    print(f"\nMethod: {reading.proposed_method}")
    print(f"\nKey Contributions:")
    for c in reading.key_contributions:
        print(f"  - {c}")
    print(f"\nExperimental Setup: {reading.experimental_setup}")
    print(f"\nMain Results: {reading.main_results}")
    print(f"\nLimitations: {reading.limitations}")
    print(f"\nComparison to Prior Work: {reading.comparison_to_prior_work}")

    if reading.experiment_table and reading.experiment_table.entries:
        print(f"\nExperiment Results:")
        for entry in reading.experiment_table.entries:
            arrow = "↑" if entry.higher_is_better else "↓"
            print(f"  {entry.benchmark} / {entry.setting} / {entry.metric}{arrow}:")
            for r in entry.results:
                tag = " [paper]" if r.is_paper_method else ""
                print(f"    {r.method_name}: {r.value}{tag}")

    if delta:
        print(f"\n{'='*60}")
        print(f"Contribution Analysis: {delta.overall_significance.upper()}")
        print(f"{'='*60}")
        if delta.novel_contributions:
            print("Novel:")
            for c in delta.novel_contributions:
                print(f"  + {c}")
        if delta.incremental_improvements:
            print("Incremental:")
            for c in delta.incremental_improvements:
                print(f"  ~ {c}")
        if delta.contradicts_prior:
            print("Contradicts prior work:")
            for c in delta.contradicts_prior:
                print(f"  ! {c}")

    if result.get("sota_report") and result["sota_report"].actions:
        print(f"\nSOTA Updates: {len(result['sota_report'].actions)} benchmarks updated")
        for action in result["sota_report"].actions:
            print(f"  [{action.action}] {action.summary}")


async def cmd_pipeline(config):
    """Run full 5-stage pipeline."""
    orch = PipelineOrchestrator(config)
    stats = await orch.run_all()
    print(f"\nPipeline complete:")
    print(f"  Crawled:      {stats['crawled']}")
    print(f"  Filtered:     {stats['filtered']}")
    print(f"  Deep read:    {stats['read']}")
    print(f"  SOTA updated: {stats['sota_updated']}")


async def cmd_sota(config):
    """Display SOTA knowledge base (markdown files)."""
    from src.knowledge.sota_tracker import SOTAKnowledgeBase

    sota_kb = SOTAKnowledgeBase(config.sota_dir, llm=None, llm_config=None)
    benchmarks = sota_kb.get_all_benchmarks()

    if not benchmarks:
        print("No SOTA data yet. Run the pipeline first.")
        return

    for name, content in benchmarks:
        print(f"\n{'='*60}")
        print(content)
        print()


def cmd_onboard(args):
    """Interactive onboarding: set up research profile via conversation."""
    import os
    from pathlib import Path

    from dotenv import load_dotenv

    from src.config import LLMConfig
    from src.onboard.advisor import ResearchAdvisor

    load_dotenv()

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set.")
        sys.exit(1)

    # Minimal config - only need LLM settings for onboarding
    config_path = args.config
    llm_config = LLMConfig(
        filter_model="gemini-2.5-flash",
        reader_model="gemini-2.5-pro",
        embedding_model="gemini-embedding-001",
        api_key=api_key,
        max_concurrent=5,
        temperature=0.3,
    )

    # If config.yaml exists, load LLM settings from it
    config_file = Path(config_path)
    if config_file.exists():
        import yaml

        with open(config_file, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        llm_raw = raw.get("llm", {})
        llm_config = LLMConfig(
            filter_model=llm_raw.get("filter_model", llm_config.filter_model),
            reader_model=llm_raw.get("reader_model", llm_config.reader_model),
            embedding_model=llm_raw.get("embedding_model", llm_config.embedding_model),
            api_key=api_key,
            max_concurrent=llm_raw.get("max_concurrent", llm_config.max_concurrent),
            temperature=llm_raw.get("temperature", llm_config.temperature),
        )

    # Load existing profile for --refine mode
    existing_profile = None
    if args.refine and config_file.exists():
        import yaml

        with open(config_file, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        topics = raw.get("topics", [])
        existing_profile = {
            "research_profile": topics[0].get("research_profile", "") if topics else "",
            "topics": topics,
            "relevance_threshold": raw.get("filter", {}).get("relevance_threshold", 6),
        }

    advisor = ResearchAdvisor(
        llm_config=llm_config,
        config_path=config_path,
        pdf_dir=Path(raw.get("pdf_dir", "data/pdfs") if config_file.exists() else "data/pdfs"),
        sota_dir=Path(raw.get("sota_dir", "data/sota") if config_file.exists() else "data/sota"),
        existing_profile=existing_profile,
    )
    advisor.run()


async def cmd_export(config, output_path: str):
    """Export knowledge data to JSON."""
    from src.storage.database import Database
    from src.storage.exporter import export_knowledge

    db = Database(config.db_path)
    await db.initialize()
    data = await export_knowledge(db, "config.yaml", config.sota_dir)

    with open(output_path, "w", encoding="utf-8") as f:
        import json
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\nExported knowledge to {output_path}")
    print(f"  Papers:              {len(data['papers'])}")
    print(f"  Relevance verdicts:  {len(data['relevance_verdicts'])}")
    print(f"  Deep readings:       {len(data['deep_readings'])}")
    print(f"  Contribution deltas: {len(data['contribution_deltas'])}")
    print(f"  SOTA tables:         {len(data['sota_tables'])}")


async def cmd_import(config, input_path: str, merge: bool):
    """Import knowledge data from JSON."""
    import json

    from src.storage.database import Database
    from src.storage.exporter import import_knowledge

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    db = Database(config.db_path)
    await db.initialize()

    mode = "merge (upsert)" if merge else "replace"
    print(f"\nImporting from {input_path} (mode: {mode})...")
    summary = await import_knowledge(db, data, config.sota_dir, merge=merge)

    print(f"\nImport complete:")
    print(f"  Papers:              {summary['papers']}")
    print(f"  Relevance verdicts:  {summary['verdicts']}")
    print(f"  Deep readings:       {summary['deep_readings']}")
    print(f"  Contribution deltas: {summary['contribution_deltas']}")
    print(f"  SOTA files:          {summary['sota_files']}")


async def cmd_stats(config):
    """Show database statistics."""
    from src.storage.database import Database

    db = Database(config.db_path)
    await db.initialize()
    stats = await db.get_stats()

    print(f"\nDatabase Statistics:")
    print(f"  Total papers:     {stats['total_papers']}")
    print(f"  Filtered:         {stats['filtered']}")
    print(f"  Deep read:        {stats['deep_read']}")
    print(f"  SOTA updates:     {stats['sota_updates']}")


def main():
    parser = argparse.ArgumentParser(
        description="RisearchAgent - ArXiv paper analysis pipeline"
    )
    parser.add_argument(
        "-c", "--config", default="config.yaml", help="Config file path"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    subparsers.add_parser("crawl", help="Crawl ArXiv papers")
    subparsers.add_parser("filter", help="Filter papers by relevance")

    read_parser = subparsers.add_parser("read", help="Deep-read a specific paper")
    read_parser.add_argument("arxiv_id", help="ArXiv paper ID (e.g. 2401.12345)")

    subparsers.add_parser("pipeline", help="Run full 5-stage pipeline")
    subparsers.add_parser("sota", help="Show SOTA tracking table")
    subparsers.add_parser("stats", help="Show database statistics")

    export_parser = subparsers.add_parser("export", help="Export knowledge data to JSON")
    export_parser.add_argument(
        "output", nargs="?", default="knowledge_export.json",
        help="Output file path (default: knowledge_export.json)",
    )

    import_parser = subparsers.add_parser("import", help="Import knowledge data from JSON")
    import_parser.add_argument("input", help="Input JSON file path")
    import_parser.add_argument(
        "--merge", action="store_true",
        help="Merge with existing data (upsert) instead of replacing",
    )

    onboard_parser = subparsers.add_parser(
        "onboard", help="Interactive onboarding: set up research profile"
    )
    onboard_parser.add_argument(
        "--refine", action="store_true",
        help="Refine existing profile instead of starting fresh",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "onboard":
        cmd_onboard(args)
        return

    config = load_config(args.config)

    commands = {
        "crawl": lambda: cmd_crawl(config),
        "filter": lambda: cmd_filter(config),
        "read": lambda: cmd_read(config, args.arxiv_id),
        "pipeline": lambda: cmd_pipeline(config),
        "sota": lambda: cmd_sota(config),
        "stats": lambda: cmd_stats(config),
        "export": lambda: cmd_export(config, args.output),
        "import": lambda: cmd_import(config, args.input, args.merge),
    }

    asyncio.run(commands[args.command]())


if __name__ == "__main__":
    main()
