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
- ``source_hook``     a hook run over the file text before it is parsed, for
                      spellings the grammar cannot handle at all; it must
                      preserve length or every span in the file shifts
- ``builtins``        names the language provides with no import; calls to
                      them are marked ``builtin:<name>``
- ``stdlib_calls``    bare names its standard library supplies; calls stay
                      ``external:`` and are listed on ``deps.stdlib_calls``
- ``entry_points``    ``names`` / ``prefixes`` / ``file_contains`` that make an
                      item an entry point; extraction stamps the reason on it

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


def builtins_for(language: str) -> frozenset[str]:
    """Names a language's runtime provides without any import: ``len``, ``Some``, ``parseInt``.

    Profiled languages declare them as ``"builtins"`` in their JSON; Python's
    native extractor computes them from the interpreter. Extraction marks a call
    to one of these ``builtin:<name>`` (see ``depmap.resolve_calls``) so that no
    analysis module has to carry any language's builtin table (#37). A language
    that declares none gets an empty set, and its runtime calls stay ``external:``.
    """
    prof = all_profiles().get(language)
    if prof is not None and prof.raw.get("builtins"):
        return frozenset(prof.raw["builtins"])
    if language == "python":
        from spindlebox.extract.py_lang import PY_BUILTINS
        return PY_BUILTINS
    return frozenset()


def stdlib_calls_for(language: str) -> frozenset[str]:
    """Bare names a language's standard library supplies: C's ``printf``, ``malloc``.

    Unlike ``builtins_for`` these are not language intrinsics, so the call edge
    stays ``external:`` (the code lives outside the project). Extraction lists
    the ones an item calls on ``deps.stdlib_calls`` so ``gaps`` can tell them
    from a typo without knowing the language (#38).
    """
    prof = all_profiles().get(language)
    if prof is not None and prof.raw.get("stdlib_calls"):
        return frozenset(prof.raw["stdlib_calls"])
    return frozenset()


def known_call_names(language: str) -> frozenset[str]:
    """Every bare name a language's runtime supplies: ``builtins`` and ``stdlib_calls``.

    Used to upgrade an index built before extraction wrote those markers.
    """
    return builtins_for(language) | stdlib_calls_for(language)


def entry_points_for(language: str) -> dict:
    """A language's entry-point conventions: ``{"names", "prefixes", "file_contains"}``.

    Profiled languages declare them as ``"entry_points"``; Python's live beside its
    native extractor. A language that declares none has no entry points but the
    ones its callers reach (#38).
    """
    prof = all_profiles().get(language)
    if prof is not None and prof.raw.get("entry_points"):
        return dict(prof.raw["entry_points"])
    if language == "python":
        from spindlebox.extract.py_lang import PY_ENTRY_POINTS
        return dict(PY_ENTRY_POINTS)
    return {}


def entry_point_reason(rule: dict, name: str, file: str) -> str | None:
    """Why an item is an entry point under ``rule`` (``name:main``, ``prefix:Test``,
    ``file:test``), or None. Name beats prefix beats file; the file rule matches a
    case-insensitive substring of the item's relative path."""
    if name in rule.get("names", ()):
        return f"name:{name}"
    for prefix in rule.get("prefixes", ()):
        if name.startswith(prefix):
            return f"prefix:{prefix}"
    lowered = file.lower()
    for part in rule.get("file_contains", ()):
        if part.lower() in lowered:
            return f"file:{part}"
    return None
