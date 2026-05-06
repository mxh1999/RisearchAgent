#!/usr/bin/env python3
"""RisearchAgent - CLI entry point."""

import argparse
import asyncio
import logging
import sys

# Force UTF-8 stdout/stderr so unicode glyphs (✓ ⚠ ─ etc) used by the
# explore / configure commands don't crash on Windows GBK consoles.
for _stream_name in ("stdout", "stderr"):
    _s = getattr(sys, _stream_name, None)
    if _s is not None and hasattr(_s, "reconfigure"):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

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


def _build_llm_config_from_env(config_path: str) -> "LLMConfig":
    """Build an LLMConfig that works whether or not config.yaml exists yet.

    The new explore/synthesize/configure stages run BEFORE config.yaml is
    written, so we can't depend on load_config(). Read from env first,
    then merge any per-key override from config.yaml if it happens to
    exist already (e.g. on a refine).
    """
    import os
    from pathlib import Path
    import yaml
    from dotenv import load_dotenv
    from src.config import LLMConfig

    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set.")
        sys.exit(1)

    cfg = {
        "filter_model": os.environ.get("GEMINI_FILTER_MODEL", "gemini-3-flash"),
        "reader_model": os.environ.get("GEMINI_READER_MODEL", "gemini-2.5-pro"),
        "embedding_model": os.environ.get(
            "GEMINI_EMBEDDING_MODEL", "gemini-embedding-001"
        ),
        "max_concurrent": 5,
        "temperature": 0.3,
    }
    cfg_path = Path(config_path)
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        # Env vars take precedence over config.yaml values for the new
        # explore flow — config.yaml may have stale model names from the
        # old onboard (e.g. gemini-2.5-flash that some providers don't carry).
        for k, v in (raw.get("llm") or {}).items():
            if k in cfg and k not in (
                "filter_model", "reader_model", "embedding_model",
            ):
                cfg[k] = v

    return LLMConfig(
        filter_model=cfg["filter_model"],
        reader_model=cfg["reader_model"],
        embedding_model=cfg["embedding_model"],
        api_key=api_key,
        max_concurrent=cfg["max_concurrent"],
        temperature=cfg["temperature"],
        base_url=os.environ.get("GEMINI_BASE_URL") or None,
        embedding_api_key=os.environ.get("GEMINI_EMBEDDING_API_KEY") or None,
        embedding_base_url=os.environ.get("GEMINI_EMBEDDING_BASE_URL") or None,
    )


async def cmd_explore(args):
    """Stage A: run Explorer with the user's intent. Persists state.json."""
    from src.explore.runner import run_explore, state_path

    llm_config = _build_llm_config_from_env(args.config)

    intent = args.intent
    if not intent:
        intent = input("Research intent: ").strip()
    if not intent:
        print("Error: empty intent.")
        sys.exit(1)

    seed_ids = args.seed.split(",") if args.seed else None
    seed_ids = [s.strip() for s in (seed_ids or []) if s.strip()] or None

    state = await run_explore(
        intent_text=intent,
        seed_arxiv_ids=seed_ids,
        llm_config=llm_config,
        action_budget=args.action_budget,
        time_budget_seconds=args.time_budget,
        read_paper_budget=args.read_budget,
        enable_clusterer=not args.no_cluster,
        enable_reader=args.enable_read,
    )

    sp = state_path(state.metadata.run_id)
    print(f"\n✓ Explore complete: run_id={state.metadata.run_id}")
    print(f"  status:  {state.metadata.status}")
    print(f"  reason:  {state.metadata.termination_reason}")
    print(f"  pool:    {state.pool_size} papers")
    print(f"  turns:   {state.turn}")
    print(f"  state:   {sp}")
    print(f"\nNext: python run.py synthesize {state.metadata.run_id}")


async def cmd_synthesize(args):
    """Stage B: synthesize FieldMap from a frozen state."""
    from src.explore.runner import (
        load_state_for,
        run_synthesize,
    )

    llm_config = _build_llm_config_from_env(args.config)
    state = load_state_for(args.run_id)

    fm, json_p, md_p = await run_synthesize(state=state, llm_config=llm_config)
    print(f"\n✓ Synthesize complete: run_id={args.run_id}")
    print(f"  sub_areas:           {len(fm.sub_areas)}")
    print(f"  dominant_benchmarks: {len(fm.dominant_benchmarks)}")
    print(f"  classic_baselines:   {len(fm.classic_baselines)}")
    print(f"  open_questions:      {len(fm.open_questions)}")
    print(f"  notes:               {len(fm.notes)}")
    print(f"  json:    {json_p}")
    print(f"  markdown: {md_p}")
    print(f"\nNext: python run.py configure {args.run_id}")


def cmd_configure(args):
    """Stage C: present FieldMap, accept edits, write config.yaml."""
    from pathlib import Path
    import yaml
    from src.configure import run_configure
    from src.explore.runner import load_field_map_for, load_state_for

    fm = load_field_map_for(args.run_id)
    try:
        state = load_state_for(args.run_id)
    except Exception:
        state = None  # OK — derive_config has a no-state fallback

    config_file = Path(args.config)
    base_config = None
    if config_file.exists():
        base_config = yaml.safe_load(config_file.read_text(encoding="utf-8")) or None

    derived = run_configure(
        fm=fm,
        state=state,
        intent_text=fm.header.intent_snippet,
        config_path=config_file,
        base_config=base_config,
    )
    if not derived:
        sys.exit(1)


async def cmd_onboard(args):
    """End-to-end: explore → synthesize → configure. The user-friendly path.

    Replaces the old conversational ResearchAdvisor (src/onboard/) per Q10
    in docs/onboard-redesign/04-open-design-questions.md. The old module
    will be removed once the new flow has been used in anger a few times.
    """
    from src.explore.runner import run_explore, run_synthesize

    llm_config = _build_llm_config_from_env(args.config)

    intent = args.intent
    if not intent:
        intent = input("Research intent: ").strip()
    if not intent:
        print("Error: empty intent.")
        sys.exit(1)

    seed_ids = args.seed.split(",") if args.seed else None
    seed_ids = [s.strip() for s in (seed_ids or []) if s.strip()] or None

    print("\n--- Stage 1/3: Explore ---")
    state = await run_explore(
        intent_text=intent,
        seed_arxiv_ids=seed_ids,
        llm_config=llm_config,
        action_budget=args.action_budget,
        time_budget_seconds=args.time_budget,
        read_paper_budget=args.read_budget,
        enable_clusterer=not args.no_cluster,
        enable_reader=args.enable_read,
    )
    print(
        f"  done: pool={state.pool_size}, turns={state.turn}, "
        f"reason={state.metadata.termination_reason}"
    )

    print("\n--- Stage 2/3: Synthesize ---")
    fm, json_p, md_p = await run_synthesize(state=state, llm_config=llm_config)
    print(f"  done: {len(fm.sub_areas)} sub-areas")
    print(f"  field map: {md_p}")

    print("\n--- Stage 3/3: Configure ---")
    # Configure is interactive — switch back to sync.
    from pathlib import Path
    import yaml
    from src.configure import run_configure

    config_file = Path(args.config)
    base_config = None
    if config_file.exists():
        base_config = yaml.safe_load(config_file.read_text(encoding="utf-8")) or None

    derived = run_configure(
        fm=fm,
        state=state,
        intent_text=fm.header.intent_snippet,
        config_path=config_file,
        base_config=base_config,
    )
    if not derived:
        print("\nOnboard incomplete (user quit at configure). State + field map were saved.")
        sys.exit(1)
    print("\n✓ Onboard complete.")


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

    # —— New explore-based onboard pipeline (Q10 replacement) ——

    def _add_explore_args(p):
        p.add_argument(
            "--seed", default=None,
            help="Comma-separated arxiv_ids to use as seed papers (optional)",
        )
        p.add_argument(
            "--action-budget", type=int, default=60,
            help="Hard cap on planner actions (default 60)",
        )
        p.add_argument(
            "--time-budget", type=int, default=900,
            help="Wall-clock budget in seconds (default 900 = 15 min)",
        )
        p.add_argument(
            "--read-budget", type=int, default=3,
            help="Max read_paper actions per run (default 3)",
        )
        p.add_argument(
            "--no-cluster", action="store_true",
            help="Disable clustering (skips cluster_refresh actions; debug-only)",
        )
        p.add_argument(
            "--enable-read", action="store_true",
            help="Enable read_paper deep-reading (off by default; expensive Pro calls)",
        )

    explore_parser = subparsers.add_parser(
        "explore",
        help="Run autonomous Explorer to survey a research field",
    )
    explore_parser.add_argument(
        "intent", nargs="?", default=None,
        help="Research intent (prompted interactively if omitted)",
    )
    _add_explore_args(explore_parser)

    syn_parser = subparsers.add_parser(
        "synthesize",
        help="Synthesize FieldMap from a completed exploration",
    )
    syn_parser.add_argument("run_id", help="Run ID from a previous explore")

    cfg_parser = subparsers.add_parser(
        "configure",
        help="Interactively configure config.yaml from a synthesized FieldMap",
    )
    cfg_parser.add_argument("run_id", help="Run ID from a previous synthesize")

    onboard_parser = subparsers.add_parser(
        "onboard",
        help="Full onboard: explore → synthesize → configure",
    )
    onboard_parser.add_argument(
        "intent", nargs="?", default=None,
        help="Research intent (prompted interactively if omitted)",
    )
    _add_explore_args(onboard_parser)

    args = parser.parse_args()
    setup_logging(args.verbose)

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # The new onboard / explore / synthesize / configure commands DON'T
    # need a config.yaml to exist — they're the path that creates it. Run
    # them without going through load_config().
    if args.command == "onboard":
        asyncio.run(cmd_onboard(args))
        return
    if args.command == "explore":
        asyncio.run(cmd_explore(args))
        return
    if args.command == "synthesize":
        asyncio.run(cmd_synthesize(args))
        return
    if args.command == "configure":
        cmd_configure(args)  # synchronous (interactive input)
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
