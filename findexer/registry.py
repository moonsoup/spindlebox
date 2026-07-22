"""Central registry of indexed projects (~/.findexer/registry.json)."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


def _home() -> Path:
    return Path(os.environ.get("FINDEXER_HOME", str(Path.home() / ".findexer")))


def _registry_path() -> Path:
    return _home() / "registry.json"


def _load() -> dict:
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
