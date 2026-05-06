"""Configure: FieldMap → user choices → config.yaml.

See docs/onboard-redesign/12-configure.md.

Public API:
  ConfigureSession           — mutable user choices
  derive_config              — pure projection FieldMap+session → config dict
  write_config_atomically    — write + .bak rotation
  run_configure              — interactive CLI (Enter to accept, edit mode)
"""

from src.configure.cli import run_configure
from src.configure.derive import derive_config, pick_anchor_paper_ids
from src.configure.session import (
    DEFAULT_ANCHOR_COUNT_PER_CLUSTER,
    DEFAULT_RELEVANCE_THRESHOLD,
    ConfigureSession,
)
from src.configure.writer import write_config_atomically

__all__ = [
    "ConfigureSession",
    "DEFAULT_ANCHOR_COUNT_PER_CLUSTER",
    "DEFAULT_RELEVANCE_THRESHOLD",
    "derive_config",
    "pick_anchor_paper_ids",
    "write_config_atomically",
    "run_configure",
]
