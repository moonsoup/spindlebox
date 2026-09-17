"""Findings: a result shape that can say what was NOT determined.

SPIndlestacks answer with a table, which is right for a census -- so many
functions, so many untyped. It is wrong for a checker, because the three things
a checker most needs to say have no column:

    a check could not run, and why          (`skipped`)
    an observation is real but not decisive (`quiet`)
    nothing was read at all                 (`scanned` is 0, not None)

Dropping those turns "we looked and found nothing" into something
indistinguishable from "we did not look", which is the failure this estate has
shipped more than once. So findings are their own schema, and
`findings.to_table` is what flattens them where a table is genuinely wanted
(csv, html) -- carrying the skipped checks across as rows of their own.

The shape is deliberately Ziggurat's `Report.as_dict()` verbatim. A second
dialect to translate between would be a second place for the meaning to drift.
"""

from __future__ import annotations

import json

#: Bumped only for a breaking change. New keys may be added without a bump; a
#: reader must ignore what it does not know.
SCHEMA = "spindlebox.findings/1"

_FINDING_KEYS = {"check", "summary", "evidence", "confidence"}


class FindingsError(ValueError):
    """A findings document that cannot be trusted to mean what it says."""


def validate(report: dict) -> None:
    """Raise unless `report` is a findings document. Cheap and structural."""
    if not isinstance(report, dict):
        raise FindingsError("a findings report is an object")
    if not isinstance(report.get("project"), str):
        raise FindingsError("'project' must be a string")

    scanned = report.get("scanned", None)
    if isinstance(scanned, bool) or not isinstance(scanned, (int, type(None))):
        raise FindingsError(
            "'scanned' is an integer, or null for 'nothing that reads files ran' "
            "-- null and 0 are different answers")

    findings = report.get("findings")
    if not isinstance(findings, list):
        raise FindingsError("'findings' must be a list")
    for item in findings:
        if not isinstance(item, dict) or not _FINDING_KEYS <= set(item):
            raise FindingsError(
                f"every finding needs {sorted(_FINDING_KEYS)}; got "
                f"{sorted(item) if isinstance(item, dict) else type(item).__name__}")

    if not isinstance(report.get("quiet", []), list):
        raise FindingsError("'quiet' must be a list")

    skipped = report.get("skipped", [])
    if not isinstance(skipped, list):
        raise FindingsError("'skipped' must be a list")
    for item in skipped:
        if not isinstance(item, dict) or {"check", "why"} - set(item):
            raise FindingsError(
                "every skipped entry is an object with 'check' and 'why' -- a "
                "check that did not run has to say why, or it reads as a pass")


def wrap(results: dict[str, dict]) -> dict:
    """Several projects' reports as one document, each validated."""
    for report in results.values():
        validate(report)
    return {"schema": SCHEMA, "results": results}


def to_rows(results: dict[str, dict]) -> tuple[list[str], list[dict]]:
    """Findings and skipped checks as table rows, for csv and html."""
    columns = ["project", "state", "check", "summary", "confidence", "files", "evidence"]
    rows: list[dict] = []
    for project, report in sorted(results.items()):
        for finding in report.get("findings", []):
            rows.append({
                "project": project,
                "state": "finding",
                "check": finding.get("check", ""),
                "summary": finding.get("summary", ""),
                "confidence": finding.get("confidence", ""),
                "files": len(finding.get("paths", []) or []),
                "evidence": finding.get("evidence", ""),
            })
        for entry in report.get("skipped", []):
            rows.append({
                "project": project,
                "state": "not checked",
                "check": entry.get("check", ""),
                "summary": entry.get("why", ""),
                "confidence": "",
                "files": 0,
                "evidence": entry.get("why", ""),
            })
    return columns, rows


def render(results: dict[str, dict], fmt: str) -> str:
    """The findings a person reads, or the document a machine reads."""
    if fmt == "json":
        return json.dumps(wrap(results), indent=1, sort_keys=True) + "\n"

    out: list[str] = []
    for project, report in sorted(results.items()):
        scanned = report.get("scanned")
        read = "" if scanned is None else (
            f" ({scanned} source file{'' if scanned == 1 else 's'} read)")
        out.append(f"## {project}{read}")
        out.append("")
        for finding in report.get("findings", []):
            out.append(f"- **{finding.get('check')}**: {finding.get('summary')}")
            if finding.get("evidence"):
                out.append(f"  - {finding['evidence']}")
            if finding.get("suggestion"):
                out.append(f"  - → {finding['suggestion']}")
        if not report.get("findings"):
            out.append("- nothing found")
        for entry in report.get("skipped", []):
            out.append(f"- _not checked_ **{entry.get('check')}**: {entry.get('why')}")
        quiet = report.get("quiet", [])
        if quiet:
            out.append(f"- _also seen, not conclusive_: {len(quiet)}")
        out.append("")
    return "\n".join(out)
