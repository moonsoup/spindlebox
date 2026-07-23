"""SPIndlestacks: reports defined as data, run as ctx-normalized op chains.

A report is a *stack* — a small JSON file in ``reporting_stacks/`` naming an
ordered chain of registered ops, exactly the SPIndleframe calling convention:
every op is ``ctx in → ctx out``, declares ``requires``/``provides`` ctx keys,
and the chain is validated (stack check) before it runs. Collectors put
``title`` / ``columns`` / ``rows`` into ctx; renderers turn those into
``output``. Adding a report = one stack file, plus a collector only if no
existing op computes what you need.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from spindlebox import registry
from spindlebox.schema import ScaIndex

STACK_DIR = Path(__file__).parent / "reporting_stacks"

REPORT_OPS: dict[str, dict] = {}


def report_op(name: str, requires: set[str] = frozenset(), provides: set[str] = frozenset()):
    def wrap(fn):
        REPORT_OPS[name] = {"fn": fn, "requires": set(requires), "provides": set(provides)}
        return fn
    return wrap


# ------------------------------------------------------------------ stacks

def list_stacks() -> dict[str, dict]:
    out = {}
    for path in sorted(STACK_DIR.glob("*.stack.json")):
        data = json.loads(path.read_text())
        out[data["report"]] = data
    return out


def check_stack(stack: dict) -> list[str]:
    """Compile-time validation: ops exist, ctx chain satisfied, ends with output."""
    errors = []
    have = set(stack.get("ctx", {})) | {"format"}
    for name in stack["stages"]:
        op = REPORT_OPS.get(name)
        if op is None:
            errors.append(f"unknown op '{name}' (have: {sorted(REPORT_OPS)})")
            continue
        missing = op["requires"] - have
        if missing:
            errors.append(f"op '{name}' requires {sorted(missing)} — not provided upstream")
        have |= op["provides"]
    if "output" not in have:
        errors.append("stack never provides 'output' (no renderer stage?)")
    return errors


def run_stack(stack: dict, overrides: dict | None = None) -> dict:
    errors = check_stack(stack)
    if errors:
        raise ValueError("; ".join(errors))
    ctx = {**stack.get("ctx", {}), **(overrides or {})}
    ctx.setdefault("format", stack.get("default_format", "md"))
    for name in stack["stages"]:
        ctx = REPORT_OPS[name]["fn"](ctx)
    return ctx


# -------------------------------------------------------------- collectors

def _iter_indexes(ctx) -> list[tuple[str, ScaIndex]]:
    """(name, index) for the selected project, or every registered project."""
    wanted = ctx.get("project")
    out = []
    for name, entry in sorted(registry.list_projects().items()):
        if wanted and name != wanted:
            continue
        path = Path(entry["index"])
        if not path.exists():
            continue
        out.append((name, ScaIndex.from_dict(json.loads(path.read_text()))))
    return out


@report_op("collect.typing_health", requires=set(), provides={"title", "columns", "rows"})
def collect_typing_health(ctx):
    """Where 'any' hides: untyped fraction per project, worst files named."""
    rows = []
    for name, idx in _iter_indexes(ctx):
        slots = 0
        anys = 0
        by_file: dict[str, list[int]] = {}
        for item in idx.items:
            f = by_file.setdefault(item.file, [0, 0])
            for p in item.signature.params:
                slots += 1
                f[0] += 1
                if "any" in p.norm_type:
                    anys += 1
                    f[1] += 1
            slots += 1
            f[0] += 1
            if "any" in item.signature.returns_norm:
                anys += 1
                f[1] += 1
        worst = sorted(by_file.items(), key=lambda kv: -kv[1][1])[:3]
        rows.append({
            "project": name,
            "items": len(idx.items),
            "type_slots": slots,
            "untyped_pct": round(100 * anys / slots, 1) if slots else 0.0,
            "worst_files": "; ".join(f"{f} ({a}/{t})" for f, (t, a) in worst if a),
        })
    ctx.update(title="Typing health — untyped ('any') share per project",
               columns=["project", "items", "type_slots", "untyped_pct", "worst_files"],
               rows=rows)
    return ctx


@report_op("collect.dup_candidates", requires=set(), provides={"title", "columns", "rows"})
def collect_dup_candidates(ctx):
    """Same signature class + same normalized name in different projects."""
    seen: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for name, idx in _iter_indexes(ctx):
        for item in idx.items:
            if item.kind not in ("function", "method"):
                continue
            key = (item.sig_class, item.name.lower().replace("_", ""))
            seen.setdefault(key, []).append((name, item.address))
    rows = []
    for (sig, _), where in sorted(seen.items()):
        projects = {p for p, _ in where}
        if len(projects) < 2:
            continue
        rows.append({
            "sig_class": sig,
            "count": len(where),
            "projects": ", ".join(sorted(projects)),
            "addresses": "; ".join(f"{p}:{a}" for p, a in where[:4]),
        })
    ctx.update(title="Duplicate candidates — same shape + name across projects",
               columns=["sig_class", "count", "projects", "addresses"], rows=rows)
    return ctx


@report_op("collect.compile_matrix", requires=set(), provides={"title", "columns", "rows"})
def collect_compile_matrix(ctx):
    """Project × output language: does a skeleton generate? (compile is the harness's job)"""
    from spindlebox.generate import BACKENDS, GenOptions
    rows = []
    for name, idx in _iter_indexes(ctx):
        row = {"project": name, "items": len(idx.items)}
        for lang in sorted(BACKENDS):
            try:
                files = BACKENDS[lang]().generate(idx, GenOptions())
                row[lang] = f"ok ({sum(len(f.content.splitlines()) for f in files)} lines)"
            except Exception as e:  # noqa: BLE001 — report, don't crash the report
                row[lang] = f"FAIL: {type(e).__name__}"
        rows.append(row)
    langs = sorted({k for r in rows for k in r} - {"project", "items"})
    ctx.update(title="Compile matrix — skeleton generation per output language",
               columns=["project", "items", *langs], rows=rows)
    return ctx


@report_op("collect.score_history", requires={"state_dir"}, provides={"title", "columns", "rows"})
def collect_score_history(ctx):
    """slamface score-per-run history from a pulled state directory."""
    rows = []
    for path in sorted(Path(ctx["state_dir"]).expanduser().glob("score-r-*.json")):
        try:
            s = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        rows.append({k: s.get(k) for k in (
            "run_id", "tier", "score", "threshold", "green", "stages", "failures",
            "spindlebox_version")})
    ctx.update(title="Score history — every slamface run",
               columns=["run_id", "tier", "score", "threshold", "green", "stages",
                        "failures", "spindlebox_version"],
               rows=rows)
    return ctx


# --------------------------------------------------------------- renderers

def _cell(v) -> str:
    return "" if v is None else str(v)


@report_op("render.table", requires={"title", "columns", "rows", "format"}, provides={"output"})
def render_table(ctx):
    """One renderer, four formats: md (default), csv, html, json."""
    fmt, title, cols, rows = ctx["format"], ctx["title"], ctx["columns"], ctx["rows"]
    if fmt == "json":
        ctx["output"] = json.dumps({"title": title, "rows": rows}, indent=1) + "\n"
    elif fmt == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
        ctx["output"] = buf.getvalue()
    elif fmt == "html":
        head = "".join(f"<th>{c}</th>" for c in cols)
        body = "\n".join(
            "<tr>" + "".join(f"<td>{_cell(r.get(c))}</td>" for c in cols) + "</tr>"
            for r in rows)
        ctx["output"] = (
            f"<!doctype html>\n<meta charset=\"utf-8\">\n<title>{title}</title>\n"
            "<style>body{font:14px/1.5 system-ui;margin:2rem}"
            "table{border-collapse:collapse}th,td{border:1px solid #999;"
            "padding:4px 10px;text-align:left}th{background:#eee}</style>\n"
            f"<h1>{title}</h1>\n<table><tr>{head}</tr>\n{body}\n</table>\n")
    else:  # md
        lines = [f"# {title}", "", "| " + " | ".join(cols) + " |",
                 "|" + "---|" * len(cols)]
        lines += ["| " + " | ".join(_cell(r.get(c)) for c in cols) + " |" for r in rows]
        ctx["output"] = "\n".join(lines) + "\n"
    return ctx
