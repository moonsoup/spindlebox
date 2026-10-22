"""The analysis layer is language-agnostic, and this file is what enforces it (#37).

Rule: any language spindlebox maps must flow through every analysis function
without changing that function. Language knowledge belongs to extraction --
profiles as data, ``spindlebox/extract/``, and the ``typenorm``/``depmap``
resolution tables -- and extraction resolves it into neutral markers
(``builtin:``, ``external:``, ``ambiguous:``, core-1 types). Analysis modules
read only those normalized fields.

Three enforcement pieces live here:

1. **The AST gate** (``scan_module`` / ``test_no_unapproved_language_knowledge``).
   Every module under ``spindlebox/`` except the extraction package and the
   output-language emitters is parsed, and four shapes of language knowledge
   are reported as hits: a comparison on a ``language``/``lang`` name or
   attribute, a string literal naming a language (or one of its aliases or
   file extensions), ``import builtins``, and any import of a ``*_lang``
   extractor module. Each hit must match an entry in the registry
   ``docs/language-agnostic-exceptions.json`` whose hash of the enclosing
   statement is still current -- so editing an excepted statement voids its
   approval, and a stale entry (nothing matches it any more) fails too.

2. **The mutation check** (``test_gate_catches_planted_language_branch``):
   planting ``if item.language == "go":`` in ``gaps.py`` produces an
   unregistered hit. This proves the gate can fail, which is the only reason
   to trust it when it passes.

3. **The parity harness** (``test_parity_*``): the same tiny program, spelled
   in every language spindlebox indexes (``tests/fixtures/miniproj_parity``),
   is run through every analysis -- ctx normalization, signature classes,
   ``validate``, ``gaps``, ``workflows``, the reporting stacks and the
   findings model -- and the language-independent projections of each
   result must be identical. The two places a language legitimately differs
   are read from its profile data, never hard-coded here: a profile whose
   call extraction is ``known_only`` cannot report unresolvable calls, and a
   ``fixed_signature`` profile requires its fixed parameters at every item.

Run ``python3 tests/test_language_agnostic.py`` to print the current hits in
registry shape; copy an entry into the registry only once a Codex verifier
has approved it through the fix-verify cycle.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
PACKAGE = REPO / "spindlebox"
REGISTRY = REPO / "docs" / "language-agnostic-exceptions.json"
FIXTURES = REPO / "tests" / "fixtures"
PARITY = FIXTURES / "miniproj_parity"

#: Where language knowledge is allowed to live, and so is not scanned.
#: ``extract/`` is the extraction layer the rule names. ``generate/`` holds the
#: output-language emitters: each one is a single language by definition.
EXEMPT_PACKAGES = ("spindlebox/extract", "spindlebox/generate")

#: The modules the issue names as the analysis layer. They are scanned like
#: every other module; this list exists so the suite can assert that each is
#: actually covered by the scan (a renamed module must not silently drop out).
ANALYSIS_MODULES = ("gaps", "workflows", "validate", "sigclass", "ctxnorm",
                    "reporting", "findings_model")

_LANGUAGE_NAMES = ("language", "lang")


# ---------------------------------------------------------------- the scanner

def language_vocabulary() -> frozenset[str]:
    """Every spelling that names an input language: profile names, aliases, extensions."""
    from spindlebox.extract import base
    from spindlebox.extract.profile_registry import all_profiles
    base._register_profiles()
    words = set(base.ALL_LANGS) | set(base.LANG_ALIASES) | set(base.EXT_MAP)
    for prof in all_profiles().values():
        words.add(prof.language)
        words.update(prof.extensions)
    return frozenset(w.lower() for w in words)


@dataclass(frozen=True)
class Hit:
    module: str      # repo-relative posix path
    kind: str        # language-compare | language-literal | builtins-import | lang-module-import
    statement: str   # first line of the enclosing statement, stripped
    hash: str        # sha256 of the enclosing statement's source, truncated
    line: int        # of the hit itself; informational, never matched on


def _names_language(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id in _LANGUAGE_NAMES
    if isinstance(node, ast.Attribute):
        return node.attr in _LANGUAGE_NAMES
    return False


def _hit_kind(node: ast.AST, vocabulary: frozenset[str]) -> str | None:
    if isinstance(node, ast.Compare):
        if any(_names_language(n) for n in (node.left, *node.comparators)):
            return "language-compare"
    elif isinstance(node, ast.Constant):
        if isinstance(node.value, str) and node.value.lower() in vocabulary:
            return "language-literal"
    elif isinstance(node, ast.Import):
        if any(a.name == "builtins" for a in node.names):
            return "builtins-import"
        if any(a.name.rsplit(".", 1)[-1].endswith("_lang") for a in node.names):
            return "lang-module-import"
    elif isinstance(node, ast.ImportFrom):
        mod = node.module or ""
        if mod == "builtins":
            return "builtins-import"
        if mod.rsplit(".", 1)[-1].endswith("_lang") or any(
                a.name.endswith("_lang") for a in node.names):
            return "lang-module-import"
    return None


def scan_source(source: str, module: str,
                vocabulary: frozenset[str] | None = None) -> list[Hit]:
    """Every language-knowledge hit in one module's source, with statement hashes."""
    vocabulary = vocabulary or language_vocabulary()
    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    hits: list[Hit] = []
    for node in ast.walk(tree):
        kind = _hit_kind(node, vocabulary)
        if kind is None:
            continue
        stmt = node
        while stmt is not None and not isinstance(stmt, ast.stmt):
            stmt = parents.get(stmt)
        if stmt is None:  # cannot happen for a well-formed module
            continue
        segment = ast.get_source_segment(source, stmt) or ""
        hits.append(Hit(
            module=module, kind=kind,
            statement=segment.splitlines()[0].strip() if segment else "",
            hash=hashlib.sha256(segment.encode()).hexdigest()[:16],
            line=getattr(node, "lineno", stmt.lineno),
        ))
    return hits


def scanned_modules() -> list[Path]:
    out = []
    for path in sorted(PACKAGE.rglob("*.py")):
        rel = path.relative_to(REPO).as_posix()
        if any(rel == pkg or rel.startswith(pkg + "/") for pkg in EXEMPT_PACKAGES):
            continue
        out.append(path)
    return out


def scan_package() -> list[Hit]:
    vocab = language_vocabulary()
    hits: list[Hit] = []
    for path in scanned_modules():
        rel = path.relative_to(REPO).as_posix()
        hits.extend(scan_source(path.read_text(), rel, vocab))
    return hits


def load_registry() -> dict:
    return json.loads(REGISTRY.read_text())


def check_against_registry(hits: list[Hit], registry: dict) -> list[str]:
    """Violations: unregistered hits, voided (edited) entries, stale entries, bad entries."""
    problems: list[str] = []
    entries = registry.get("exceptions", [])
    approved: dict[tuple[str, str], dict] = {}
    for entry in entries:
        for field in ("module", "statement", "hash", "kinds", "reason", "approval"):
            if not entry.get(field):
                problems.append(f"registry entry {entry.get('module')!r}: missing {field!r}")
        approval = entry.get("approval") or {}
        for field in ("verifier", "cycle", "contract", "issue", "round"):
            if not approval.get(field):
                problems.append(
                    f"registry entry {entry.get('module')!r} "
                    f"{entry.get('statement')!r}: approval lacks {field!r}")
        approved[(entry.get("module"), entry.get("hash"))] = entry

    matched: set[tuple[str, str]] = set()
    for hit in hits:
        key = (hit.module, hit.hash)
        entry = approved.get(key)
        if entry is None:
            problems.append(
                f"{hit.module}:{hit.line} [{hit.kind}] {hit.statement!r} is not an "
                "approved exception (move it into extraction, or get a Codex "
                "fix-verify approval and register it with this hash: "
                f"{hit.hash})")
            continue
        matched.add(key)
        if hit.kind not in entry.get("kinds", []):
            problems.append(
                f"{hit.module}:{hit.line} {hit.statement!r}: registered kinds "
                f"{entry.get('kinds')} do not cover {hit.kind!r}")
        if entry.get("statement") != hit.statement:
            problems.append(
                f"{hit.module}: entry hash {hit.hash} matches but its 'statement' "
                f"{entry.get('statement')!r} is not {hit.statement!r}")
    for key, entry in approved.items():
        if key not in matched:
            problems.append(
                f"registry entry {entry.get('module')} {entry.get('statement')!r} "
                f"(hash {entry.get('hash')}) matches nothing: the excepted code was "
                "edited or removed, which voids its approval -- re-approve with the "
                "new hash, or delete the entry")
    return problems


# ------------------------------------------------------------------- the gate

def test_registry_is_well_formed():
    reg = load_registry()
    assert reg.get("schema") == "spindlebox.language-agnostic-exceptions/1"
    assert isinstance(reg.get("exceptions"), list)
    assert reg.get("rule"), "the registry states the rule it excepts from"


def test_scan_covers_every_analysis_module():
    scanned = {p.stem for p in scanned_modules()}
    missing = set(ANALYSIS_MODULES) - scanned
    assert not missing, f"analysis modules not covered by the gate: {sorted(missing)}"
    for future in ("callgraph", "fntables"):
        if (PACKAGE / f"{future}.py").exists():
            assert future in scanned


def test_no_unapproved_language_knowledge():
    problems = check_against_registry(scan_package(), load_registry())
    assert not problems, "\n".join(problems)


def test_analysis_modules_carry_no_language_knowledge_at_all():
    """Stricter than the registry for the seven analysis modules: an exception
    there would be the rule failing, so not even an approved one is accepted."""
    reg = load_registry()
    analysis = {f"spindlebox/{m}.py" for m in ANALYSIS_MODULES}
    hits = [h for h in scan_package() if h.module in analysis]
    assert not hits, "\n".join(f"{h.module}:{h.line} [{h.kind}] {h.statement}" for h in hits)
    excepted = [e for e in reg["exceptions"] if e.get("module") in analysis]
    assert not excepted, f"analysis modules may not hold exceptions: {excepted}"


def test_gate_catches_planted_language_branch():
    """The mutation check from the issue: ``if item.language == "go":`` in gaps.py."""
    source = (PACKAGE / "gaps.py").read_text()
    needle = "def _is_entrypoint(item: Item) -> bool:\n"
    assert needle in source
    planted = source.replace(
        needle, needle + '    if item.language == "go":\n        return True\n', 1)
    hits = scan_source(planted, "spindlebox/gaps.py")
    kinds = {h.kind for h in hits}
    assert {"language-compare", "language-literal"} <= kinds
    problems = check_against_registry(hits, load_registry())
    assert any("not an approved exception" in p for p in problems)


def test_gate_catches_every_hit_shape():
    vocab = language_vocabulary()
    src = (
        "import builtins\n"
        "from spindlebox.extract.py_lang import extract_python_file\n"
        "import spindlebox.extract.go_lang\n"
        "def f(item, lang):\n"
        "    if lang in ('python', 'go'):\n"
        "        return item.language != 'rust'\n"
        "    return item.file.endswith('.py')\n"
    )
    kinds = {h.kind for h in scan_source(src, "x.py", vocab)}
    assert kinds == {"builtins-import", "lang-module-import",
                     "language-compare", "language-literal"}


def test_editing_an_excepted_statement_voids_it():
    """A registry hash is the statement's hash: change one character, lose approval."""
    vocab = language_vocabulary()
    src = "def f(language):\n    if language == 'python':\n        return 1\n    return 0\n"
    (hit,) = {h.hash: h for h in scan_source(src, "x.py", vocab)}.values()
    reg = {"schema": "spindlebox.language-agnostic-exceptions/1", "rule": "r",
           "exceptions": [{"module": "x.py", "statement": hit.statement, "hash": hit.hash,
                           "kinds": ["language-compare", "language-literal"], "reason": "r",
                           "approval": {"verifier": "codex", "cycle": "fix-verify",
                                        "contract": "c", "issue": 1, "round": 1}}]}
    assert check_against_registry(scan_source(src, "x.py", vocab), reg) == []
    edited = src.replace("return 1", "return 2")
    problems = check_against_registry(scan_source(edited, "x.py", vocab), reg)
    assert any("not an approved exception" in p for p in problems)
    assert any("voids its approval" in p for p in problems)


# ------------------------------------------------------------ parity harness

def parity_languages() -> list[str]:
    from spindlebox.extract import base
    from spindlebox.extract.profile_registry import all_profiles
    base._register_profiles()
    return sorted(set(base.ALL_LANGS) | set(all_profiles()))


def _profile(lang: str):
    from spindlebox.extract.profile_registry import profile_for
    return profile_for(lang)


def _expected_unresolvable(lang: str) -> set[str]:
    """A ``known_only`` call extractor never emits an unknown callee, by its own data."""
    prof = _profile(lang)
    if prof is not None and prof.calls.get("known_only"):
        return set()
    return {"does_not_exist"}


def _expected_unprovided(lang: str) -> set[str]:
    """A fixed-signature language requires its fixed params at every item."""
    prof = _profile(lang)
    if prof is not None and prof.fixed_signature:
        return {p["name"] for p in prof.fixed_signature.get("params", [])}
    return set()


PROGRAM = {"load", "clean", "summarize", "compute_alpha", "compute_beta", "island", "main"}
DEAD = {"compute_alpha", "compute_beta", "island"}
DUPLICATES = [{"compute_alpha", "compute_beta"}]
FLOWS = {("main", "load", "clean"), ("main", "summarize", "clean"),
         ("compute_alpha", "clean"), ("compute_beta", "clean")}


@pytest.fixture(scope="module")
def parity_indexes():
    from spindlebox.extract import build_index
    out = {}
    for lang in parity_languages():
        out[lang] = build_index(PARITY / lang, project_name=f"parity_{lang}", langs=[lang])
    return out


def test_parity_fixture_covers_every_language():
    missing = [lang for lang in parity_languages()
               if not any(p.is_file() for p in (PARITY / lang).glob("*"))]
    assert not missing, f"no parity program for: {missing}"


def test_parity_extraction(parity_indexes):
    for lang, idx in parity_indexes.items():
        assert {it.name for it in idx.items} == PROGRAM, lang
        assert {it.language for it in idx.items} == {lang}


def test_parity_ctxnorm(parity_indexes):
    for lang, idx in parity_indexes.items():
        for it in idx.items:
            assert set(it.ctx_adapter.requires) <= _expected_unprovided(lang), (lang, it.name)
            for key in it.ctx_adapter.provides:
                assert key == f"{it.name}_result", (lang, it.name, key)


def test_parity_sigclass(parity_indexes):
    from spindlebox.sigclass import build_signature_classes
    for lang, idx in parity_indexes.items():
        by_name = {it.name: it for it in idx.items}
        assert by_name["compute_alpha"].sig_class == by_name["compute_beta"].sig_class, lang
        classes = build_signature_classes(idx.items)
        members = classes[by_name["compute_alpha"].sig_class]["members"]
        assert {by_name["compute_alpha"].ordinal, by_name["compute_beta"].ordinal} <= set(members)


def test_parity_validate(parity_indexes):
    from spindlebox.validate import validate_index
    for lang, idx in parity_indexes.items():
        errors, _warnings = validate_index(idx)
        assert errors == [], (lang, errors)


def test_parity_gaps(parity_indexes):
    from spindlebox.gaps import find_gaps
    for lang, idx in parity_indexes.items():
        name_of = {it.address: it.name for it in idx.items}
        gaps = find_gaps(idx)
        dead = {name_of[g["address"]] for g in gaps if g["kind"] == "dead_item"}
        assert dead == DEAD, (lang, dead)
        unresolved = {g["detail"] for g in gaps if g["kind"] == "unresolvable_call"}
        assert unresolved == _expected_unresolvable(lang), (lang, unresolved)
        dups = [{name_of[m] for m in g["members"]} for g in gaps if g["kind"] == "near_duplicate"]
        assert dups == DUPLICATES, (lang, dups)
        unprovided = {g["detail"] for g in gaps if g["kind"] == "unprovided_ctx_key"}
        assert unprovided == _expected_unprovided(lang), (lang, unprovided)


def test_parity_workflows(parity_indexes):
    from spindlebox.workflows import mine_workflows
    scored: dict[str, dict[tuple, float]] = {}
    for lang, idx in parity_indexes.items():
        name_of = {it.address: it.name for it in idx.items}
        flows = mine_workflows(idx)
        scored[lang] = {tuple(name_of[a] for a in f["addresses"]): f["strength"] for f in flows}
        assert set(scored[lang]) == FLOWS, (lang, set(scored[lang]))
    reference = next(iter(scored.values()))
    for lang, table in scored.items():
        assert table == reference, (lang, table)


def test_parity_findings_model(parity_indexes):
    from spindlebox import findings_model
    from spindlebox.gaps import find_gaps
    results = {}
    for lang, idx in parity_indexes.items():
        results[f"parity_{lang}"] = {
            "project": f"parity_{lang}", "scanned": len({it.file for it in idx.items}),
            "findings": [{"check": g["kind"], "summary": g["detail"],
                          "evidence": g.get("address", ""), "confidence": g["severity"]}
                         for g in find_gaps(idx)],
        }
        findings_model.validate(results[f"parity_{lang}"])
    doc = json.loads(findings_model.render(results, "json"))
    assert set(doc["results"]) == {f"parity_{lang}" for lang in parity_indexes}
    assert findings_model.render(results, "md").count("## parity_") == len(parity_indexes)


def test_parity_reporting(parity_indexes, tmp_path, monkeypatch):
    """Every stack that needs nothing but indexes runs over every language's index."""
    monkeypatch.setenv("SPINDLEBOX_HOME", str(tmp_path / "home"))
    from spindlebox import registry, reporting
    for lang, idx in parity_indexes.items():
        out = tmp_path / lang / ".spi" / "index.json"
        out.parent.mkdir(parents=True)
        out.write_text(json.dumps(idx.to_dict()))
        registry.register(f"parity_{lang}", str(tmp_path / lang), str(out))
    stacks = reporting.list_stacks()
    for name in ("typing-health", "dup-candidates", "compile-matrix"):
        ctx = reporting.run_stack(stacks[name], {"format": "json"})
        rows = json.loads(ctx["output"])["rows"]
        assert rows, name
        if name == "typing-health":
            assert {r["project"] for r in rows} == {f"parity_{lang}" for lang in parity_indexes}
        if name == "compile-matrix":
            failed = [(r["project"], k, v) for r in rows for k, v in r.items()
                      if isinstance(v, str) and v.startswith("FAIL")]
            assert not failed, failed


# ------------------------------------------------------------------ emitter

if __name__ == "__main__":
    entries = []
    seen: set[tuple[str, str]] = set()
    for h in scan_package():
        if (h.module, h.hash) in seen:
            continue
        seen.add((h.module, h.hash))
        d = asdict(h)
        del d["line"]
        d["kinds"] = sorted({x.kind for x in scan_package() if (x.module, x.hash) == (h.module, h.hash)})
        del d["kind"]
        d["reason"] = "<why this cannot move into extraction>"
        d["approval"] = {"verifier": "codex", "cycle": "fix-verify", "contract": "<contract>",
                         "issue": 0, "round": 0}
        entries.append(d)
    json.dump({"exceptions": entries}, sys.stdout, indent=2)
    print()
