"""The guide's examples are enforced, not aspirational.

Every ``$ spindlebox ...`` block in docs/guide/*.md and docs/REPORTING.md is
executed against the fixture projects in an isolated registry; the documented
output must match as a shape (``...`` elides volatile text). Options tables are
checked against ``--help`` in both directions, quoted profile fragments against
the real JSON, and every relative markdown link against the tree.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
DOCS = sorted((REPO / "docs" / "guide").glob("*.md")) + [REPO / "docs" / "REPORTING.md"]
FIXTURES = REPO / "tests" / "fixtures"

# a '    $ spindlebox' line starts a new example; indented non-'$' lines are its
# expected output (blank lines allowed between output chunks)
_BLOCK = re.compile(r"^    \$ (spindlebox .+)\n((?:^    (?!\$ ).*\n|^\n(?=    ))*)", re.M)


def _examples():
    out = []
    for doc in DOCS:
        for m in _BLOCK.finditer(doc.read_text()):
            expected = [line[4:] for line in m.group(2).splitlines()
                        if line.startswith("    ")]
            out.append(pytest.param(doc.name, m.group(1), expected,
                                    id=f"{doc.stem}:{m.group(1)[:48]}"))
    assert out, "no runnable examples found in the guide"
    return out


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Fixture projects indexed into an isolated registry, like the guide says."""
    root = tmp_path_factory.mktemp("docsworld")
    env_home = root / "home"
    for proj in ("miniproj_py", "miniproj_mixed", "miniproj_gaps"):
        dst = root / proj
        shutil.copytree(FIXTURES / proj, dst)
        shutil.rmtree(dst / ".spi", ignore_errors=True)
    for proj in ("miniproj_py", "miniproj_mixed", "miniproj_gaps"):
        r = _run(f"spindlebox index {proj} --name {proj}", root, env_home)
        assert r.returncode == 0, r.stderr
    return root, env_home


def _run(cmd: str, cwd: Path, home: Path) -> subprocess.CompletedProcess:
    # the docs show shell commands — parse them exactly as a shell would
    argv = [sys.executable, "-m", "spindlebox", *shlex.split(cmd)[1:]]
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                          env={"PATH": "/usr/bin:/bin", "SPINDLEBOX_HOME": str(home),
                               "HOME": str(home)})


def _shape_regex(lines: list[str]) -> re.Pattern:
    parts = []
    for line in lines:
        esc = re.escape(line.rstrip())
        parts.append(esc.replace(re.escape("..."), ".*"))
    return re.compile(".*".join(parts), re.S)


@pytest.mark.parametrize("doc,cmd,expected", _examples())
def test_documented_example_is_truthful(world, doc, cmd, expected):
    root, home = world
    r = _run(cmd, root, home)
    combined = r.stdout + r.stderr
    # documented failure demos (INVALID) must fail; everything else must succeed
    wants_failure = any("INVALID" in line for line in expected)
    if wants_failure:
        assert r.returncode != 0, f"{cmd!r} was documented as failing but exited 0"
    else:
        assert r.returncode == 0, f"{cmd!r} exited {r.returncode}:\n{combined}"
    if expected:
        pat = _shape_regex(expected)
        assert pat.search(combined), (
            f"output of {cmd!r} does not match the documented shape.\n"
            f"documented:\n" + "\n".join(expected) + f"\n\nactual:\n{combined}")


_CMD_DOCS = {
    "querying.md": ["index", "show", "search", "deps"],
    "model.md": ["validate", "call", "pipeline"],
    "generating.md": ["generate"],
    "analysis.md": ["gaps", "workflows"],
}
_FLAG = re.compile(r"`(--[a-z-]+)`")


@pytest.mark.parametrize("doc,commands", _CMD_DOCS.items(), ids=_CMD_DOCS)
def test_options_tables_match_help(doc, commands):
    text = (REPO / "docs" / "guide" / doc).read_text()
    for cmd in commands:
        r = subprocess.run([sys.executable, "-m", "spindlebox", cmd, "--help"],
                           capture_output=True, text=True)
        help_flags = set(re.findall(r"--[a-z-]+", r.stdout)) - {"--help"}
        # section = from '## spindlebox <cmd>' to the next '## '
        m = re.search(rf"^## spindlebox {cmd}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
        assert m, f"{doc} lacks a section for {cmd}"
        doc_flags = set(_FLAG.findall(m.group(1)))
        missing_from_doc = help_flags - doc_flags
        assert not missing_from_doc, f"{cmd}: flags in --help but not documented: {missing_from_doc}"
        phantom = {f for f in doc_flags if f not in help_flags
                   and f not in ("--all-projects",)} - set(_FLAG.findall(text))
        assert not phantom, f"{cmd}: documented flags that don't exist: {phantom}"


def test_pipeline_and_projects_subcommands_documented():
    model = (REPO / "docs" / "guide" / "model.md").read_text()
    for sub in ("define", "check", "list"):
        assert f"pipeline {sub}" in model
    hk = (REPO / "docs" / "guide" / "housekeeping.md").read_text()
    for sub in ("list", "add", "remove"):
        assert f"projects {sub}" in hk


def test_quoted_profile_fragments_are_real():
    lang_doc = (REPO / "docs" / "guide" / "languages.md").read_text()
    go = json.loads((REPO / "spindlebox/extract/profiles/go.json").read_text())
    java = json.loads((REPO / "spindlebox/extract/profiles/java.json").read_text())
    emit = json.loads((REPO / "spindlebox/generate/emit_profiles/java.json").read_text())

    assert go["boundaries"] == ["func_literal", "function_declaration", "method_declaration"]
    assert go["declarations"]["method_declaration"] == {"handler": "go_method"}
    assert go["returns_norm_hook"] == "go_multi_return"
    assert java["instance"]["member_prefix"] == "this."
    assert java["types"]["simple"]["String"] == "str"
    assert emit["ident"]["escape"] == {"style": "suffix", "with": "_"}
    for flag in ("reserved_member_names", "unique_result_binding", "reserve_ancestor_names"):
        assert flag in lang_doc and flag in emit["ident"]
    assert emit["types"]["containers"]["list"]["format"] == "java.util.List<{0}>"


_LINK = re.compile(r"\]\((?!https?://|#)([^)#]+)(#[^)]*)?\)")


def test_relative_links_resolve():
    md_files = list((REPO / "docs").rglob("*.md")) + [REPO / "README.md"]
    broken = []
    for f in md_files:
        for m in _LINK.finditer(f.read_text()):
            target = (f.parent / m.group(1)).resolve()
            if not target.exists():
                broken.append(f"{f.relative_to(REPO)} -> {m.group(1)}")
    assert not broken, "broken relative links:\n" + "\n".join(broken)
