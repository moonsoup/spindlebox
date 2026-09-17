"""Which projects a run is about.

Three sources, in a fixed order of precedence: one `root`, every directory
`under` a root, or the registry. The registry path differs from
`reporting._iter_indexes` in one way that matters: a project it cannot use is
REPORTED as skipped rather than dropped in silence, and a project with no index
is still a project -- a checker that reads source does not need the SPI at all.
"""

from __future__ import annotations

from pathlib import Path

from spindlebox import registry


class NoSuchProject(ValueError):
    """A path was named explicitly and is not there."""


def _entry(root: Path, name: str | None = None) -> dict:
    index = root / ".spi" / "index.json"
    return {"name": name or root.name, "root": str(root),
            "index": str(index) if index.is_file() else None}


def select_projects(ctx: dict) -> dict:
    """ctx in → ctx out, with `projects` and `skipped`."""
    projects: list[dict] = []
    skipped: list[dict] = []

    if ctx.get("root"):
        root = Path(ctx["root"]).expanduser().resolve()
        if not root.is_dir():
            raise NoSuchProject(f"{root} is not a directory")
        projects.append(_entry(root))
    elif ctx.get("under"):
        under = Path(ctx["under"]).expanduser().resolve()
        if not under.is_dir():
            raise NoSuchProject(f"{under} is not a directory")
        # Hidden directories are tooling, not projects.
        projects.extend(_entry(p) for p in sorted(under.iterdir())
                        if p.is_dir() and not p.name.startswith("."))
    else:
        for name, info in sorted(registry.list_projects().items()):
            root = Path(info["root"]).expanduser()
            if not root.is_dir():
                skipped.append({"check": "select.projects",
                                "why": f"{name}: {root} is gone"})
                continue
            projects.append(_entry(root, name))

    ctx["projects"] = projects
    ctx["skipped"] = ctx.get("skipped", []) + skipped
    return ctx
