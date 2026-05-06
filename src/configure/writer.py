"""Atomic writer for config.yaml + .bak rotation.

Per docs/onboard-redesign/12-configure.md "Atomic 写入". Writes the new
config to a tempfile in the same directory then `os.replace`s it onto the
target path. If the target already existed, the previous version is
saved alongside as `config.yaml.bak.<timestamp>` BEFORE the replace, so
the user can roll back even if something goes wrong mid-write.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import yaml


logger = logging.getLogger(__name__)


def write_config_atomically(path: Path, data: dict) -> Path | None:
    """Write `data` to `path`. Returns the .bak path if a backup was made.

    1. If `path` exists, copy it to `<path>.bak.<ISO-timestamp>` first.
    2. Render `data` to YAML in a tempfile in the same directory.
    3. os.replace tempfile → path (atomic on POSIX & Windows 3.3+).
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    backup_path: Path | None = None
    if path.exists():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = path.with_name(f"{path.name}.bak.{ts}")
        shutil.copy2(path, backup_path)
        logger.info("[configure.writer] backed up existing config to %s", backup_path)

    yaml_text = yaml.dump(
        data,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=120,
    )

    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        delete=False,
        dir=path.parent,
        prefix=path.stem + ".",
        suffix=".tmp",
    )
    try:
        tmp.write(yaml_text)
        tmp.flush()
        tmp.close()
        Path(tmp.name).replace(path)
    except Exception:
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except Exception:
            pass
        raise

    return backup_path


__all__ = ["write_config_atomically"]
