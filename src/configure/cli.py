"""Interactive Configure CLI: review → optional edit → accept → write.

Per docs/onboard-redesign/12-configure.md happy path:

    [Enter] accept defaults and write config.yaml
    [e]     edit interactively
    [q]     quit without saving

Edit mode commands (M8 v1):
    list, show <slug>, select <slugs>, select all, select none,
    drop <slug>, rename <slug> "<label>", threshold <n>, anchors <slug> <n>,
    preview, accept, cancel, help

Deferred to v1.1+: merge / split (need LLM / mini-clusterer).
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import Callable, Optional

from src.configure.derive import derive_config
from src.configure.session import (
    DEFAULT_ANCHOR_COUNT_PER_CLUSTER,
    DEFAULT_RELEVANCE_THRESHOLD,
    ConfigureSession,
)
from src.configure.writer import write_config_atomically
from src.explore.state import ExplorationState
from src.synthesize.types import FieldMap


# Input/output abstraction for testability — default = stdin/stdout via print/input.
InputFn = Callable[[str], str]
OutputFn = Callable[[str], None]


def _default_input(prompt: str) -> str:
    return input(prompt)


def _default_output(text: str) -> None:
    print(text, flush=True)


# —————————————————————————————————————————————————————————————
# Public entry
# —————————————————————————————————————————————————————————————


def run_configure(
    fm: FieldMap,
    state: Optional[ExplorationState],
    intent_text: str,
    config_path: Path,
    *,
    base_config: Optional[dict] = None,
    input_fn: InputFn = _default_input,
    output_fn: OutputFn = _default_output,
) -> dict:
    """Drive the interactive Configure flow. Returns the written config dict.

    Returns an empty dict if the user quits without saving.
    """
    session = ConfigureSession.from_field_map(fm)
    all_subareas = [sa.slug for sa in fm.sub_areas]

    _print_summary(fm, session, output_fn)

    while True:
        choice = input_fn("\n[Enter] accept  [e] edit  [q] quit  > ").strip().lower()
        if choice in ("", "y", "yes", "accept"):
            return _commit(fm, state, session, intent_text, config_path,
                           base_config=base_config, output_fn=output_fn)
        if choice in ("q", "quit", "exit"):
            output_fn("Aborted; no changes written.")
            return {}
        if choice in ("e", "edit"):
            if _edit_loop(fm, session, all_subareas, input_fn, output_fn):
                # accept inside edit loop
                return _commit(fm, state, session, intent_text, config_path,
                               base_config=base_config, output_fn=output_fn)
            else:
                output_fn("Aborted; no changes written.")
                return {}
        output_fn(f"Unknown choice {choice!r}. Type Enter / e / q.")


# —————————————————————————————————————————————————————————————
# Summary + preview
# —————————————————————————————————————————————————————————————


def _print_summary(
    fm: FieldMap, session: ConfigureSession, output_fn: OutputFn
) -> None:
    n_clusters = len(fm.sub_areas)
    n_selected = sum(1 for sa in fm.sub_areas if session.is_selected(sa.slug))
    n_papers = fm.header.n_papers_surveyed

    output_fn("")
    output_fn("╭─ Field Map Summary " + "─" * 40)
    output_fn(f"│ Intent: {fm.header.intent_snippet}")
    output_fn(f"│ {n_clusters} clusters, {n_papers} papers surveyed")
    output_fn(f"│")
    output_fn(f"│ Selected ({n_selected}/{n_clusters}):")
    for sa in fm.sub_areas:
        marker = "☑" if session.is_selected(sa.slug) else "☐"
        label = session.label_for(sa.slug, sa.display_label)
        size = len(sa.representative_papers)
        output_fn(f"│   {marker} {sa.slug:24s}  {label}  ({size} reps)")
    output_fn(f"│")
    output_fn(f"│ Threshold: {session.relevance_threshold}")
    output_fn("╰" + "─" * 60)


def _print_preview(
    fm: FieldMap,
    state: Optional[ExplorationState],
    session: ConfigureSession,
    intent_text: str,
    output_fn: OutputFn,
) -> None:
    import yaml

    derived = derive_config(fm, session, intent_text, state=state)
    output_fn("")
    output_fn("--- config.yaml preview (topics + filter only) ---")
    excerpt = {"topics": derived.get("topics"), "filter": derived.get("filter")}
    output_fn(yaml.dump(excerpt, default_flow_style=False, allow_unicode=True,
                        sort_keys=False, width=120))


# —————————————————————————————————————————————————————————————
# Edit loop
# —————————————————————————————————————————————————————————————


HELP_TEXT = """
Commands:
  list                      reprint summary
  show <slug>               show one cluster's detail
  select <s1,s2,...>        track only these slugs
  select all | select none  bulk
  drop <slug>               unselect this slug
  rename <slug> "<label>"   change display label
  threshold <n>             relevance threshold (0-10)
  anchors <slug> <n>        anchor paper count for SOTA seeding
  preview                   show derived config.yaml topics + filter
  accept                    write config.yaml and exit
  cancel                    discard edits and return to top-level prompt
  help                      this list
""".strip()


def _edit_loop(
    fm: FieldMap,
    session: ConfigureSession,
    all_subareas: list[str],
    input_fn: InputFn,
    output_fn: OutputFn,
) -> bool:
    """Returns True if user accepted, False if they cancelled."""
    output_fn(HELP_TEXT)
    while True:
        try:
            raw = input_fn("\nconfigure> ").strip()
        except EOFError:
            return False
        if not raw:
            continue
        try:
            tokens = shlex.split(raw)
        except ValueError as e:
            output_fn(f"parse error: {e}")
            continue

        verb = tokens[0].lower()
        args = tokens[1:]

        try:
            if verb in ("help", "?"):
                output_fn(HELP_TEXT)
            elif verb == "list":
                _print_summary(fm, session, output_fn)
            elif verb == "show":
                if not args:
                    output_fn("usage: show <slug>")
                else:
                    _show_one(fm, args[0], output_fn)
            elif verb == "select":
                if args == ["all"]:
                    session.select_all(all_subareas)
                elif args == ["none"]:
                    session.select_none()
                elif args:
                    # Allow both `select a,b,c` and `select a b c`
                    raw_slugs: list[str] = []
                    for a in args:
                        raw_slugs.extend(s.strip() for s in a.split(",") if s.strip())
                    session.select(raw_slugs, all_subareas)
                else:
                    output_fn("usage: select <slug,...> | select all | select none")
            elif verb == "drop":
                if not args:
                    output_fn("usage: drop <slug>")
                else:
                    session.drop(args[0])
            elif verb == "rename":
                if len(args) < 2:
                    output_fn('usage: rename <slug> "<label>"')
                else:
                    session.rename(args[0], " ".join(args[1:]), all_subareas)
            elif verb == "threshold":
                if not args:
                    output_fn("usage: threshold <0-10>")
                else:
                    session.set_threshold(int(args[0]))
            elif verb == "anchors":
                if len(args) != 2:
                    output_fn("usage: anchors <slug> <n>")
                else:
                    session.set_anchor_count(args[0], int(args[1]), all_subareas)
            elif verb == "preview":
                _print_preview(fm, None, session, "", output_fn)
            elif verb == "accept":
                return True
            elif verb in ("cancel", "quit", "q"):
                return False
            else:
                output_fn(f"unknown command: {verb!r}. Type 'help' for list.")
        except (ValueError, KeyError) as e:
            output_fn(f"error: {e}")


def _show_one(fm: FieldMap, slug: str, output_fn: OutputFn) -> None:
    sa = next((s for s in fm.sub_areas if s.slug == slug), None)
    if sa is None:
        output_fn(f"unknown slug: {slug}")
        return
    output_fn(f"\n### {sa.slug} — {sa.display_label}")
    output_fn(sa.description)
    output_fn("\nRepresentative papers:")
    for p in sa.representative_papers:
        output_fn(f"  - {p.arxiv_id}: {p.title}")
    if sa.shared_benchmarks:
        output_fn(f"Benchmarks: {', '.join(sa.shared_benchmarks)}")
    if sa.active_authors:
        output_fn(f"Authors:    {', '.join(sa.active_authors)}")
    output_fn(f"Year range: {sa.year_range[0]}–{sa.year_range[1]}")


# —————————————————————————————————————————————————————————————
# Commit
# —————————————————————————————————————————————————————————————


def _commit(
    fm: FieldMap,
    state: Optional[ExplorationState],
    session: ConfigureSession,
    intent_text: str,
    config_path: Path,
    *,
    base_config: Optional[dict] = None,
    output_fn: OutputFn = _default_output,
) -> dict:
    derived = derive_config(fm, session, intent_text,
                            state=state, base_config=base_config)
    backup_path = write_config_atomically(config_path, derived)
    session.mark_committed()

    output_fn("")
    output_fn(f"✓ wrote {len(derived.get('topics', []))} topics → {config_path}")
    if backup_path is not None:
        output_fn(f"  (previous config backed up at {backup_path})")
    output_fn(
        f"  threshold={derived['filter']['relevance_threshold']} "
        f"borderline_min={derived['filter']['borderline_min']}"
    )
    output_fn("")
    output_fn(
        "Note: SOTA seeding (deep-reading anchor papers) is not run in M8 v1. "
        "Use `python run.py read <arxiv_id>` for individual anchors until "
        "`run.py seed-sota <run_id>` is implemented."
    )
    return derived


__all__ = ["run_configure"]
