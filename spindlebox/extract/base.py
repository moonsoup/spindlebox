"""Shared extraction types and file discovery."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

EXT_MAP = {
    ".py": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".sh": "bash", ".bash": "bash",
}

LANG_ALIASES = {
    "py": "python", "js": "javascript", "ts": "typescript",
    "rs": "rust", "sh": "bash", "golang": "go",
}

ALL_LANGS = ["python", "javascript", "typescript", "go", "rust", "bash"]

_EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__",
    "target", "dist", "build", ".sca", ".pytest_cache", ".ruff_cache",
    "vendor", ".next", ".tox", "site-packages",
}

STATE_TO_TRAIT = {
    "pure": "fn",
    "reads_captured": "Fn",
    "reads_instance": "Fn",
    "mutates_captured": "FnMut",
    "mutates_instance": "FnMut",
    "consumes": "FnOnce",
}


@dataclass
class RawParam:
    name: str
    raw_type: str | None = None
    default: str | None = None
    kind: str = "positional"


@dataclass
class RawDecl:
    """Language-neutral function declaration as pulled straight from source."""

    name: str
    kind: str                    # function|method|closure|lambda|script_main
    language: str
    file: str                    # path relative to project root
    start_line: int
    end_line: int
    scope_chain: list[str] = field(default_factory=list)   # all enclosing scopes
    class_chain: list[str] = field(default_factory=list)   # enclosing classes only
    params: list[RawParam] = field(default_factory=list)
    returns_raw: str | None = None
    returns_norm: str | None = None      # override when set (go multi-return, bash)
    is_async: bool = False
    doc: str | None = None
    body_text: str = ""
    calls: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    state_capture: str = "pure"


def normalize_langs(langs: list[str] | None) -> list[str]:
    if not langs:
        return list(ALL_LANGS)
    out = []
    for lang in langs:
        lang = LANG_ALIASES.get(lang.strip().lower(), lang.strip().lower())
        if lang not in ALL_LANGS:
            raise ValueError(f"unknown language '{lang}' (known: {ALL_LANGS})")
        if lang not in out:
            out.append(lang)
    return out


def discover_files(root: Path, langs: list[str]) -> list[tuple[str, str]]:
    """(relative path, language) for every indexable file under root.

    Uses git's file list when root is a repo (respects .gitignore), else walks.
    """
    wanted = set(langs)
    rels: list[str] = []
    if (root / ".git").exists():
        proc = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root, capture_output=True, text=True,
        )
        if proc.returncode == 0:
            rels = [line for line in proc.stdout.splitlines() if line]
    if not rels:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            parts = path.relative_to(root).parts
            if any(p in _EXCLUDE_DIRS for p in parts[:-1]):
                continue
            rels.append("/".join(parts))
    out = []
    for rel in sorted(rels):
        lang = EXT_MAP.get(Path(rel).suffix.lower())
        if lang in wanted and (root / rel).is_file():
            out.append((rel, lang))
    return out
