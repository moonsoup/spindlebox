"""Central registry of indexed projects (~/.spindlebox/registry.json).

Legacy support: reads SPINDLEBOX_HOME first, then FINDEXER_HOME; a pre-rebrand
~/.findexer/registry.json is migrated to ~/.spindlebox/ on first load.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path


def _home() -> Path:
    for var in ("SPINDLEBOX_HOME", "FINDEXER_HOME"):
        if var in os.environ:
            return Path(os.environ[var])
    return Path.home() / ".spindlebox"


def _registry_path() -> Path:
    return _home() / "registry.json"


def _migrate_legacy() -> None:
    if "SPINDLEBOX_HOME" in os.environ or "FINDEXER_HOME" in os.environ:
        return  # explicit home override: never pull in the default legacy registry
    new = _registry_path()
    if new.exists():
        return
    legacy = Path.home() / ".findexer" / "registry.json"
    if legacy.exists():
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, new)


def _load() -> dict:
    _migrate_legacy()
    path = _registry_path()
    if not path.exists():
        return {"projects": {}}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"projects": {}}


def _save(data: dict) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1) + "\n")
    tmp.replace(path)


def list_projects() -> dict[str, dict]:
    return _load()["projects"]


def register(name: str, root: str, index_path: str) -> None:
    data = _load()
    data["projects"][name] = {
        "root": str(root),
        "index": str(index_path),
        "last_indexed": datetime.now().isoformat(timespec="seconds"),
    }
    _save(data)


def unregister(name: str) -> None:
    data = _load()
    data["projects"].pop(name, None)
    _save(data)
