"""Explorer: autonomous research field exploration.

See docs/onboard-redesign/ for the full design.

Module layout:
    state      — ExplorationState and sub-types (per 05-state-schema.md)
    actions    — 9 action types with discriminated union (per 06-action-system.md)
    spec/      — Runtime constraint rules (per 07-spec-rules.md)
    planner    — LLM-driven action proposer (per 08-planner-prompt.md)
    executor   — Action handlers
    cluster/   — HDBSCAN + slug labeling (per 09-clusterer.md)
    orchestrator — main loop wiring it all together
    checkpoint — JSON serialization for state
"""

SCHEMA_VERSION = 1
