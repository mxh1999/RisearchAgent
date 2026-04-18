"""State serialization and checkpointing.

Per docs/onboard-redesign/08, every action writes state to disk as JSON.
No pickle — cross-version stable, human-readable, easy to diff.
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

from src.explore.state import ExplorationState


logger = logging.getLogger(__name__)


def save_checkpoint(state: ExplorationState, path: Path) -> None:
    """Atomically write the state to `path` as JSON.

    Writes to a tempfile in the same directory, then os.replace for atomicity.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    json_text = state.model_dump_json(indent=2)

    # NamedTemporaryFile with delete=False so we can replace manually on Windows+POSIX
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        delete=False,
        dir=path.parent,
        prefix=path.stem + ".",
        suffix=".tmp",
    )
    try:
        tmp.write(json_text)
        tmp.flush()
        tmp.close()
        Path(tmp.name).replace(path)
    except Exception:
        # Best-effort cleanup
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except Exception:
            pass
        raise


def load_checkpoint(path: Path) -> ExplorationState:
    """Load state from disk. Raises if schema_version mismatches current."""
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    saved_version = data.get("schema_version", 0)
    from src.explore import SCHEMA_VERSION

    if saved_version != SCHEMA_VERSION:
        raise ValueError(
            f"Checkpoint schema_version={saved_version} does not match "
            f"code SCHEMA_VERSION={SCHEMA_VERSION}. "
            f"Migration not implemented yet."
        )
    return ExplorationState.model_validate(data)


def checkpoint_path_for(run_id: str, base_dir: Path = Path("data/explore/state")) -> Path:
    return base_dir / f"{run_id}.json"
