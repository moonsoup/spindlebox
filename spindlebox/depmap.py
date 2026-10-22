"""Dependency mapping: env vars, external packages, intra-index call resolution."""

from __future__ import annotations

import re
import sys

_ENV_PATTERNS: dict[str, list[re.Pattern]] = {
    "python": [
        re.compile(r"os\.environ\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\]"),
        re.compile(r"os\.environ\.get\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
        re.compile(r"os\.getenv\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
    ],
    "javascript": [
        re.compile(r"process\.env\.([A-Za-z_][A-Za-z0-9_]*)"),
        re.compile(r"process\.env\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\]"),
        re.compile(r"Deno\.env\.get\(\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]"),
    ],
    "go": [
        re.compile(r"os\.(?:Getenv|LookupEnv)\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\""),
    ],
    "rust": [
        re.compile(r"env::var(?:_os)?\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\""),
        re.compile(r"(?:option_)?env!\(\s*\"([A-Za-z_][A-Za-z0-9_]*)\""),
    ],
    "bash": [
        # uppercase-only convention: lowercase $vars are almost always locals
        re.compile(r"\$\{([A-Z][A-Z0-9_]+)[}:\-]"),
        re.compile(r"\$([A-Z][A-Z0-9_]+)"),
    ],
}
_ENV_PATTERNS["typescript"] = _ENV_PATTERNS["javascript"]
_ENV_PATTERNS["tsx"] = _ENV_PATTERNS["javascript"]

_RUST_BUILTIN_ROOTS = {"crate", "self", "super", "std", "core", "alloc", "test", "proc_macro"}

# Registered by declarative language profiles (profile_registry) — never
# consulted for the languages hardcoded above, so existing behavior is fixed.
_PROFILE_ENV: dict[str, list[re.Pattern]] = {}
_PROFILE_IMPORTS: dict[str, dict] = {}


#: Every separator an import path is split on to find its root. A profile's
#: ``external_imports`` rule may add its own via ``separators`` (#38).
_IMPORT_SEPARATORS: list[str] = [".", "/", "::"]


def register_deps(language: str, env_patterns: list[str], imports_rule: dict | None) -> None:
    _PROFILE_ENV[language] = [re.compile(p) for p in env_patterns]
    if imports_rule:
        _PROFILE_IMPORTS[language] = imports_rule
        for sep in imports_rule.get("separators", ()):
            if sep not in _IMPORT_SEPARATORS:
                _IMPORT_SEPARATORS.append(sep)


def _split_pattern(separators) -> re.Pattern:
    # longest first, so "::" is never consumed as two ":"
    seps = sorted(separators, key=len, reverse=True)
    return re.compile("|".join(re.escape(s) for s in seps))


def import_root(imp: str, separators: list[str] | tuple[str, ...] | None = None) -> str:
    """The first segment of an import path: ``acme`` of ``acme.x``, ``acme/x``, ``acme::x``.

    ``separators`` defaults to every separator any language spindlebox knows
    declares, so a caller needs no knowledge of which language wrote ``imp``.
    """
    return _split_pattern(separators or _IMPORT_SEPARATORS).split(imp, 1)[0]


def _profile_external(imp: str, rule: dict, local_roots: set[str]) -> str | None:
    """A profile rule that names its ``separators``: the external package ``imp``
    pulls in, or None. Splits on those separators where the default rule splits
    on ``.`` only; ``drop_last_segment`` drops the last segment after the last one."""
    seps = rule["separators"]
    root = import_root(imp, seps)
    if root in rule.get("stdlib_roots", ()) or root in local_roots:
        return None
    if rule.get("drop_last_segment"):
        cuts = [m.start() for m in _split_pattern(seps).finditer(imp)]
        if cuts:
            return imp[:cuts[-1]]
    return imp


def find_env_vars(body: str, language: str) -> list[str]:
    found: set[str] = set()
    pats = _ENV_PATTERNS.get(language)
    if pats is None:
        pats = _PROFILE_ENV.get(language, [])
    for pat in pats:
        found.update(pat.findall(body))
    return sorted(found)


def external_packages(imports: list[str], language: str, local_roots: set[str]) -> list[str]:
    """Reduce raw import paths to the external package names they pull in."""
    ext: set[str] = set()
    for imp in imports:
        imp = imp.strip()
        if not imp:
            continue
        rule = _PROFILE_IMPORTS.get(language)
        if rule is not None and rule.get("separators"):
            pkg = _profile_external(imp, rule, local_roots)
            if pkg is not None:
                ext.add(pkg)
            continue
        if language == "python":
            root = imp.split(".")[0]
            if root not in sys.stdlib_module_names and root not in local_roots:
                ext.add(root)
        elif language in ("javascript", "typescript", "tsx"):
            if imp.startswith((".", "/")) or imp.startswith("node:"):
                continue
            parts = imp.split("/")
            ext.add("/".join(parts[:2]) if imp.startswith("@") else parts[0])
        elif language == "go":
            root = imp.split("/")[0]
            if "." in root and root not in local_roots:
                ext.add(imp)
        elif language == "rust":
            root = imp.split("::")[0]
            if root not in _RUST_BUILTIN_ROOTS and root not in local_roots:
                ext.add(root)
        elif language == "bash":
            ext.add(imp)
        elif language in _PROFILE_IMPORTS:
            rule = _PROFILE_IMPORTS[language]
            root = imp.split(".")[0]
            if root in rule.get("stdlib_roots", ()) or root in local_roots:
                continue
            pkg = imp.rsplit(".", 1)[0] if rule.get("drop_last_segment") and "." in imp else imp
            ext.add(pkg)
    return sorted(ext)


def resolve_calls(
    raw_calls: list[str],
    caller_group: str,
    addresses_by_name: dict[str, list[str]],
    builtins: frozenset[str] | set[str] | None = None,
) -> list[str]:
    """Map raw called names to intra-index addresses where resolvable.

    Resolution: same-module item of that name first, then a globally unique
    name match. After that the two remaining cases are deliberately distinct:

    - ``ambiguous:<raw>`` — the name IS defined in this index, more than once,
      and nothing disambiguates the call site. The edge is real but its target
      is uncertain, so callers can still treat every same-named item as
      possibly-called rather than losing the edge outright.
    - ``builtin:<raw>`` — the name (or its first dotted segment) is one the
      language provides without an import, per ``builtins`` when given. The
      caller supplies that set from the item's language profile, so this
      marker is the only place a builtin is told apart from a typo: ``gaps``
      used to apply Python's builtins to every language, which flagged Go's
      ``append``, Rust's ``Some`` and JavaScript's ``parseInt`` as
      unresolvable (#37). With ``builtins`` omitted nothing is marked and the
      output is exactly what it always was.
    - ``external:<raw>`` — the name is not in the index at all: a stdlib or
      third-party call, a builtin the caller did not declare, or a typo.

    Collapsing the first case into the second was the cause of #17. Because
    ``name`` is the last dotted segment, every class sharing a ``close()``
    collides, so the discarded edges were concentrated on the commonest names.
    """
    resolved: list[str] = []
    for raw in raw_calls:
        name = raw.rsplit(".", 1)[-1]
        candidates = addresses_by_name.get(name, [])
        same_module = [a for a in candidates if a.startswith(caller_group + ".")]
        if len(same_module) == 1:
            resolved.append(same_module[0])
        elif len(candidates) == 1:
            resolved.append(candidates[0])
        elif candidates:
            resolved.append(f"ambiguous:{raw}")
        elif builtins and raw.split(".", 1)[0] in builtins:
            resolved.append(f"builtin:{raw}")
        else:
            resolved.append(f"external:{raw}")
    seen: set[str] = set()
    out = []
    for r in resolved:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out
