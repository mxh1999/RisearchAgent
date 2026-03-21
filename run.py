#!/usr/bin/env python3
"""Paper Reader Agent - CLI entry point."""

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

    if reading.extracted_benchmarks:
        print(f"\nBenchmarks:")
        for b in reading.extracted_benchmarks:
            sota_tag = " [SOTA]" if b.is_sota else ""
            print(f"  - {b.benchmark_name} / {b.metric_name}: {b.value}{b.unit}{sota_tag}")

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

    if result["sota_updates"]:
        print(f"\nSOTA Updates: {len(result['sota_updates'])} new records")


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
    """Display SOTA tracking table."""
    from src.storage.database import Database

    db = Database(config.db_path)
    await db.initialize()
    entries = await db.get_all_sota_entries()

    if not entries:
        print("No SOTA entries yet. Run the pipeline first.")
        return

    print(f"\n{'Field':<20} {'Benchmark':<25} {'Metric':<15} {'Best':<10} {'Method':<30} {'Paper'}")
    print("-" * 110)
    for e in entries:
        prev = f" (prev: {e.previous_best_value})" if e.previous_best_value else ""
        print(
            f"{e.field:<20} {e.benchmark:<25} {e.metric:<15} "
            f"{e.best_value:<10.2f} {e.best_method:<30} {e.best_paper_id}{prev}"
        )


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
    print(f"  SOTA entries:     {stats['sota_entries']}")


def main():
    parser = argparse.ArgumentParser(
        description="Paper Reader Agent - ArXiv paper analysis pipeline"
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

    args = parser.parse_args()
    setup_logging(args.verbose)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    config = load_config(args.config)

    commands = {
        "crawl": lambda: cmd_crawl(config),
        "filter": lambda: cmd_filter(config),
        "read": lambda: cmd_read(config, args.arxiv_id),
        "pipeline": lambda: cmd_pipeline(config),
        "sota": lambda: cmd_sota(config),
        "stats": lambda: cmd_stats(config),
    }

    asyncio.run(commands[args.command]())


if __name__ == "__main__":
    main()
