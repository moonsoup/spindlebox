"""Findings as a first-class result shape, beside the tabular reports.

A table can say what was found. It cannot say that a check could not run, or
that an observation was real but not decisive, or that nothing was read at all
-- and those are exactly the things a silent checker gets wrong. So the schema
carries them, and `findings.to_table` is what flattens them for csv/html.
"""

from __future__ import annotations

import json

import pytest

from spindlebox import findings_model as fm
from spindlebox import reporting

REPORT = {
    "project": "alpha",
    "scanned": 122,
    "findings": [{
        "check": "scattered-path",
        "summary": "records/ is written into 5 files, as 5 different paths",
        "evidence": "records/ is named in 5 separate files: a.py, b.py ...",
        "confidence": "structural fact",
        "paths": ["a.py", "b.py"],
        "suggestion": "give the directory one name in a config module",
        "detail": {"names": ["records/a.jsonl"], "named_bare_only": []},
    }],
    "quiet": [{"name": "host", "declared_in": "config.py", "read_by": ["a.py"]}],
    "skipped": [{"check": "change-coupling", "why": "alpha is not a git repository"}],
}


def test_a_ziggurat_shaped_report_validates() -> None:
    fm.validate(REPORT)


def test_scanned_may_be_absent_but_not_a_lie() -> None:
    """None means nothing that reads files ran. Zero means it read nothing.
    Collapsing them is how "found nothing" and "looked at nothing" became the
    same sentence."""
    fm.validate({**REPORT, "scanned": None})
    with pytest.raises(fm.FindingsError):
        fm.validate({**REPORT, "scanned": "122"})


@pytest.mark.parametrize("bad", [
    {"project": "a"},
    {**REPORT, "findings": [{"check": "x"}]},
    {**REPORT, "skipped": [["change-coupling", "why"]]},
    {**REPORT, "quiet": {}},
])
def test_a_malformed_report_is_refused(bad) -> None:
    with pytest.raises(fm.FindingsError):
        fm.validate(bad)


def test_the_wrapper_names_its_schema_and_keys_by_project() -> None:
    wrapped = fm.wrap({"alpha": REPORT})
    assert wrapped["schema"] == fm.SCHEMA
    assert wrapped["results"]["alpha"]["scanned"] == 122
    json.dumps(wrapped)  # it is a report for a reader that is not a person


# --- the ops ----------------------------------------------------------------

def test_findings_render_as_json_through_the_op() -> None:
    ctx = reporting.REPORT_OPS["render.findings"]["fn"](
        {"results": {"alpha": REPORT}, "format": "json"})
    assert json.loads(ctx["output"])["results"]["alpha"]["findings"][0]["check"] \
        == "scattered-path"


def test_findings_render_as_markdown_through_the_op() -> None:
    ctx = reporting.REPORT_OPS["render.findings"]["fn"](
        {"results": {"alpha": REPORT}, "format": "md"})
    assert "records/" in ctx["output"] and "alpha" in ctx["output"]


def test_a_skipped_check_survives_the_flattening_to_a_table() -> None:
    """The reason to have the op at all: csv and html go through render.table,
    and a check that could not run must not vanish on the way."""
    ctx = reporting.REPORT_OPS["findings.to_table"]["fn"]({"results": {"alpha": REPORT}})
    kinds = {row.get("check") for row in ctx["rows"]}
    assert {"scattered-path", "change-coupling"} <= kinds
    skipped = [r for r in ctx["rows"] if r["check"] == "change-coupling"][0]
    assert "not a git repository" in json.dumps(skipped)
    assert ctx["columns"] and ctx["title"]


def test_the_table_op_satisfies_what_render_table_requires() -> None:
    provides = reporting.REPORT_OPS["findings.to_table"]["provides"]
    # `format` is seeded by run_stack from the stack's default, not by an op.
    needs = reporting.REPORT_OPS["render.table"]["requires"] - {"format"}
    assert needs <= provides
