"""Declarative language profiles: load, validate, and register.

A language profile is a JSON file in ``spindlebox/extract/profiles/`` that
describes everything spindlebox needs to support an input language:

- ``extensions``      file extensions mapped to the language
- ``grammar``         tree-sitter wheel module and entry attribute
- ``walker``          when true, extraction runs through the generic
                      profile-driven walker (``profile_lang.py``)
- node-role tables    which node types are declarations / containers /
                      scope boundaries, and which fields hold names,
                      params, returns, bodies
- ``types``           a core-1 normalization table (registered into
                      ``typenorm``), or a reference to a legacy per-language
                      normalizer that stays in code
- ``hooks``           names of functions from the shared hook library for
                      the few genuinely language-specific behaviors

Adding a new input language should normally mean adding one JSON profile and
pinning one grammar wheel — no new Python module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from spindlebox import depmap, typenorm

PROFILE_DIR = Path(__file__).parent / "profiles"


@dataclass
class LanguageProfile:
    language: str
    extensions: list[str]
    grammar: dict | None = None          # {"module": ..., "attr": ...}
    walker: bool = False
    mode: str = "nested"                 # "nested" | "flat"
    boundaries: list[str] = field(default_factory=list)
    containers: dict = field(default_factory=dict)
    declarations: dict = field(default_factory=dict)
    params: dict = field(default_factory=dict)
    fixed_signature: dict | None = None
    declare: dict = field(default_factory=dict)
    writes: dict = field(default_factory=dict)
    instance: dict = field(default_factory=dict)
    calls: dict = field(default_factory=dict)
    imports: list = field(default_factory=list)
    imports_hook: str | None = None
    doc: dict = field(default_factory=dict)
    returns_norm_hook: str | None = None
    types: dict | None = None
    raw: dict = field(default_factory=dict)


_PROFILES: dict[str, LanguageProfile] | None = None


def _load(path: Path) -> LanguageProfile:
    data = json.loads(path.read_text())
    known = {f for f in LanguageProfile.__dataclass_fields__ if f != "raw"}
    kwargs = {k: v for k, v in data.items() if k in known}
    prof = LanguageProfile(raw=data, **kwargs)
    if not prof.language or not prof.extensions:
        raise ValueError(f"profile {path.name}: 'language' and 'extensions' are required")
    return prof


def all_profiles() -> dict[str, LanguageProfile]:
    """Load every profile once; register type tables with typenorm."""
    global _PROFILES
    if _PROFILES is None:
        _PROFILES = {}
        if PROFILE_DIR.is_dir():
            for path in sorted(PROFILE_DIR.glob("*.json")):
                prof = _load(path)
                _PROFILES[prof.language] = prof
                if prof.types and prof.types.get("mode") == "table":
                    typenorm.register_table(prof.language, prof.types)
                elif prof.types and prof.types.get("mode") == "fixed":
                    typenorm.register_fixed(prof.language, prof.types["value"])
                if prof.raw.get("env_patterns") or prof.raw.get("external_imports"):
                    depmap.register_deps(
                        prof.language,
                        prof.raw.get("env_patterns", []),
                        prof.raw.get("external_imports"),
                    )
    return _PROFILES


def profile_for(language: str) -> LanguageProfile | None:
    return all_profiles().get(language)


def grammar_for(name: str) -> dict | None:
    prof = all_profiles().get(name)
    return prof.grammar if prof is not None else None
