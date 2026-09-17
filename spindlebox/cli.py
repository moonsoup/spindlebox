"""SPIndlebox CLI — single entry point for all SPI (Serialized Process Index) operations."""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path

import spindlebox
from spindlebox import registry, staleness, workflows
from spindlebox.addresses import parse_selector
from spindlebox.dispatch import DispatchError, call_item, resolve_item
from spindlebox.extract import build_index
from spindlebox.schema import Pipeline, ScaIndex, SchemaError
from spindlebox.validate import validate_index


class CliError(Exception):
    pass


# ------------------------------------------------------------ index loading

def _index_path_for_root(root: Path) -> Path:
    """Where new indexes are written: .spi/index.json (SPI = Serialized Process Index)."""
    return root / ".spi" / "index.json"


def _existing_index_path(root: Path) -> Path | None:
    """Find a readable index: .spi first, then legacy .sca from pre-rebrand builds."""
    for rel in (".spi/index.json", ".sca/index.json"):
        candidate = root / rel
        if candidate.exists():
            return candidate
    return None


def _find_root_upwards(start: Path) -> Path | None:
    cur = start.resolve()
    for candidate in [cur, *cur.parents]:
        if _existing_index_path(candidate) is not None:
            return candidate
    return None


def _load_project(args) -> tuple[ScaIndex, Path]:
    project = getattr(args, "project", None)
    if project:
        entry = registry.list_projects().get(project)
        if entry is None:
            raise CliError(f"project '{project}' is not registered (spindlebox projects list)")
        return ScaIndex.load(entry["index"]), Path(entry["root"])
    path = Path(getattr(args, "path", None) or ".")
    root = _find_root_upwards(path)
    if root is None:
        raise CliError(
            f"no .spi/index.json (or legacy .sca/) found at or above {path.resolve()}; "
            "run 'spindlebox index <path>' or pass --project"
        )
    return ScaIndex.load(_existing_index_path(root)), root


def _warn_if_stale(idx: ScaIndex, root: Path, items, fail: bool = False) -> bool:
    """Warn when displayed items come from files that changed since indexing.

    Returns True when the caller should exit non-zero (only under --fail-on-stale).
    A span from a changed file points at whatever now occupies those lines, so
    saying nothing is the one unacceptable option (#15).
    """
    if not idx.files and not staleness.tracks_files(idx):
        print(
            "warning: index has no file metadata (built before staleness tracking) — "
            "spans are unverified; re-index to enable checking",
            file=sys.stderr,
        )
        return fail
    stale = sorted({i.file for i in items if staleness.is_stale(idx, root, i.file)})
    if not stale:
        return False
    shown = ", ".join(stale[:5])
    if len(stale) > 5:
        shown += f" (+{len(stale) - 5} more)"
    print(
        f"warning: {len(stale)} file(s) changed since indexing — spans may be wrong: "
        f"{shown}\n         refresh with: spindlebox index {root}",
        file=sys.stderr,
    )
    return fail


# ------------------------------------------------------------ commands

def cmd_stale(args) -> int:
    """Report whether an index still matches the working tree."""
    idx, root = _load_project(args)
    current = None
    if args.check_new:
        from spindlebox.extract.base import discover_files, normalize_langs

        current = [rel for rel, _lang in discover_files(root, normalize_langs(None))]
    report = staleness.stale_report(idx, root, current=current)
    if args.json:
        print(json.dumps(report, indent=1))
    else:
        print(staleness.format_report(report, root))
    return 0 if report["ok"] else 1


def cmd_index(args) -> int:
    root = Path(args.path).resolve()
    if not root.is_dir():
        raise CliError(f"not a directory: {root}")
    index_path = _index_path_for_root(root)
    old = None
    old_path = _existing_index_path(root)  # .spi, or legacy .sca (ordinals survive rebrand)
    if old_path is not None:
        try:
            old = ScaIndex.load(old_path)
        except SchemaError as e:
            print(f"warning: existing index unreadable, rebuilding fresh ({e})", file=sys.stderr)
    name = args.name or root.name
    idx = build_index(root, project_name=name, langs=args.langs.split(",") if args.langs else None,
                      old_index=old, with_source=getattr(args, "with_source", False))
    errors, warnings = validate_index(idx, strict=args.strict)
    idx.save(index_path)
    if not args.no_register:
        registry.register(name, str(root), str(index_path))
    langs = sorted({i.language for i in idx.items})
    print(
        f"indexed {name}: {len(idx.items)} items, "
        f"{len(idx.signature_classes)} signature classes, "
        f"{len(idx.ctx_schema)} ctx keys, languages: {', '.join(langs) or 'none'}"
    )
    for e in getattr(idx, "parse_errors", []):
        print(f"  skipped: {e}", file=sys.stderr)
    if idx.parse_errors:
        print(f"  NOTE: {len(idx.parse_errors)} file(s) skipped — recorded in the "
              f"index; 'validate' warns, '--strict' fails on them", file=sys.stderr)
    for w in warnings if args.verbose else []:
        print(f"  warning: {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"  error: {e}", file=sys.stderr)
        return 1
    return 0


def _select_items(idx: ScaIndex, selector: str | None, args) -> list:
    items = idx.items
    if selector:
        sel = parse_selector(selector)
        if isinstance(sel, list):
            wanted = set(sel)
            items = [i for i in items if i.ordinal in wanted]
        else:
            exact = idx.item_by_address(sel)
            if exact:
                items = [exact]
            else:
                items = [
                    i for i in items
                    if i.group == sel or i.group.startswith(sel + ".")
                    or i.address.startswith(sel + ".")
                ]
    if getattr(args, "group", None):
        items = [i for i in items if i.group == args.group or i.group.startswith(args.group + ".")]
    if getattr(args, "sig_class", None):
        items = [i for i in items if i.sig_class == args.sig_class]
    if getattr(args, "lang", None):
        items = [i for i in items if i.language == args.lang]
    if getattr(args, "name", None):
        items = [i for i in items if fnmatch.fnmatch(i.name, args.name)]
    if getattr(args, "state_capture", None):
        items = [i for i in items if i.state_capture == args.state_capture]
    return items


def _item_line(item) -> str:
    doc = f"  — {item.doc}" if item.doc else ""
    return (
        f"{item.ordinal:>5}  {item.address}  {item.sig_class}  "
        f"[{item.language}/{item.kind}/{item.state_capture}→{item.rust_fn_trait}]{doc}"
    )


def _deps_block(item, indent="       ") -> str:
    d = item.deps
    lines = []
    if d.calls:
        lines.append(f"{indent}calls: {', '.join(d.calls)}")
    if d.external_packages:
        lines.append(f"{indent}packages: {', '.join(d.external_packages)}")
    if d.env_vars:
        lines.append(f"{indent}env: {', '.join(d.env_vars)}")
    if d.ctx_keys_required:
        lines.append(f"{indent}ctx requires: {', '.join(d.ctx_keys_required)}")
    return "\n".join(lines)


def cmd_show(args) -> int:
    idx, _root = _load_project(args)
    items = _select_items(idx, args.selector, args)
    if not items:
        print("no items match", file=sys.stderr)
        return 1
    stale_fail = _warn_if_stale(idx, _root, items, getattr(args, "fail_on_stale", False))
    if getattr(args, "span", False):
        # exactly what a targeted read needs, without an ad-hoc JSON pipe
        for item in items:
            print(f"{item.file}\t{item.span[0]}\t{item.span[1]}\t{item.address}")
        return 1 if stale_fail else 0
    if args.json:
        print(json.dumps([i.to_dict() for i in items], indent=1))
        return 1 if stale_fail else 0
    for item in items:
        print(_item_line(item))
        if args.full:
            print(json.dumps(item.to_dict(), indent=2))
        elif args.deps:
            block = _deps_block(item)
            if block:
                print(block)
    return 1 if stale_fail else 0


def cmd_search(args) -> int:
    query = args.query.lower()
    targets: list[tuple[str, ScaIndex]] = []
    if args.all_projects:
        for name, entry in sorted(registry.list_projects().items()):
            try:
                targets.append((name, ScaIndex.load(entry["index"])))
            except SchemaError as e:
                print(f"warning: skipping '{name}': {e}", file=sys.stderr)
    else:
        idx, _ = _load_project(args)
        targets.append((idx.project_name, idx))
    results = []
    for pname, idx in targets:
        for item in idx.items:
            if getattr(args, "no_tests", False) and registry.is_test_address(item.address):
                continue
            if args.sig_class and item.sig_class != args.sig_class:
                continue
            if args.lang and item.language != args.lang:
                continue
            hay_doc = (item.doc or "").lower()
            if query == item.name.lower():
                score = 3
            elif query in item.name.lower():
                score = 2
            elif query in item.address.lower() or query in hay_doc:
                score = 1
            else:
                continue
            results.append((score, pname, item))
    if not results:
        print("no matches")
        return 0
    results.sort(key=lambda r: (-r[0], r[1], r[2].address))
    if args.json:
        print(json.dumps(
            [{"project": p, **i.to_dict()} for _, p, i in results[: args.limit]], indent=1
        ))
        return 0
    for _score, pname, item in results[: args.limit]:
        print(f"{pname}:{_item_line(item).lstrip()}")
    return 0


def cmd_deps(args) -> int:
    idx, _root = _load_project(args)
    item = resolve_item(idx, args.selector)
    _warn_if_stale(idx, _root, [item], fail=False)
    if args.reverse:
        callers = [i for i in idx.items if item.address in i.deps.calls]
        # An `ambiguous:` edge names something this index defines more than once, so the
        # call is real but its target is uncertain. Reporting these separately keeps the
        # certain list exact while no longer hiding the edge entirely (#17).
        possible = [
            i for i in idx.items
            if i.address != item.address and i not in callers
            and any(c.startswith("ambiguous:")
                    and c[len("ambiguous:"):].rsplit(".", 1)[-1] == item.name
                    for c in i.deps.calls)
        ]
        print(f"callers of {item.address}:")
        for c in callers:
            print(_item_line(c))
        if not callers:
            print("  (none in index)")
        if possible:
            print(f"possible callers (call named '{item.name}' is ambiguous in this index):")
            for c in possible:
                print(_item_line(c))
        return 0
    print(_item_line(item))
    d = item.deps
    print(f"  imports: {', '.join(d.imports) or '-'}")
    print(f"  external packages: {', '.join(d.external_packages) or '-'}")
    print(f"  env vars: {', '.join(d.env_vars) or '-'}")
    print(f"  calls: {', '.join(d.calls) or '-'}")
    print(f"  ctx requires: {json.dumps(item.ctx_adapter.requires)}")
    print(f"  ctx provides: {json.dumps(item.ctx_adapter.provides)}")
    return 0


def cmd_validate(args) -> int:
    if args.path:
        root = Path(args.path).resolve()
        index_path = _index_path_for_root(root)
        if not index_path.exists():
            raise CliError(f"no index at {index_path}")
        idx = ScaIndex.load(index_path)
    else:
        idx, _ = _load_project(args)
    errors, warnings = validate_index(idx, strict=args.strict)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    for e in errors:
        print(f"error: {e}", file=sys.stderr)
    if errors:
        print(f"INVALID: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1
    print(f"valid: {len(idx.items)} items, {len(warnings)} warning(s)")
    return 0


def cmd_call(args) -> int:
    idx, root = _load_project(args)
    try:
        ctx = json.loads(args.ctx)
    except json.JSONDecodeError as e:
        raise CliError(f"--ctx is not valid JSON: {e}") from e
    if not isinstance(ctx, dict):
        raise CliError("--ctx must be a JSON object")
    out = call_item(idx, root, args.selector, ctx)
    print(json.dumps(out, indent=1, default=str))
    return 0


def cmd_pipeline(args) -> int:
    idx, root = _load_project(args)
    index_path = _index_path_for_root(root)
    if args.pipe_cmd == "list":
        if not idx.pipelines:
            print("no pipelines defined")
        for p in idx.pipelines:
            stages = " → ".join(
                (idx.item_by_ordinal(o).address if idx.item_by_ordinal(o) else f"?{o}")
                for o in p.stages
            )
            print(f"{p.name}: {stages} [{'checked' if p.checked else 'unchecked'}]")
        return 0
    if args.pipe_cmd == "define":
        ordinals = [resolve_item(idx, s).ordinal for s in args.stages]
        idx.pipelines = [p for p in idx.pipelines if p.name != args.name]
        idx.pipelines.append(Pipeline(name=args.name, stages=ordinals, checked=False))
        errors, _ = validate_index(idx)
        pipe_errors = [e for e in errors if f"pipeline '{args.name}'" in e]
        if pipe_errors:
            for e in pipe_errors:
                print(f"error: {e}", file=sys.stderr)
            return 1
        idx.pipelines[-1].checked = True
        from spindlebox.validate import pipeline_edges
        stage_items = [idx.item_by_ordinal(o) for o in ordinals]
        idx.pipelines[-1].edges = pipeline_edges(stage_items)
        idx.save(index_path)
        n_edges = len(idx.pipelines[-1].edges)
        print(f"pipeline '{args.name}' defined and type-checked "
              f"({len(ordinals)} stages, {n_edges} data-flow edge(s))")
        return 0
    if args.pipe_cmd == "run":
        from spindlebox.dispatch import run_pipeline
        try:
            ctx = json.loads(args.ctx)
        except json.JSONDecodeError as e:
            raise CliError(f"--ctx is not valid JSON: {e}") from e
        if not isinstance(ctx, dict):
            raise CliError("--ctx must be a JSON object")
        result = run_pipeline(idx, root, args.name, ctx)
        print(json.dumps(result, indent=1, default=str))
        return 0
    if args.pipe_cmd == "check":
        errors, _ = validate_index(idx)
        pipe_errors = [e for e in errors if f"pipeline '{args.name}'" in e]
        for e in pipe_errors:
            print(f"error: {e}", file=sys.stderr)
        if pipe_errors:
            return 1
        if not any(p.name == args.name for p in idx.pipelines):
            raise CliError(f"no pipeline named '{args.name}'")
        print(f"pipeline '{args.name}' is type-sound")
        return 0
    raise CliError(f"unknown pipeline command {args.pipe_cmd}")


def cmd_projects(args) -> int:
    if args.proj_cmd == "add":
        index_path = _existing_index_path(Path(args.path).resolve())
        if index_path is None:
            raise CliError(f"no index under {args.path}; run spindlebox index first")
        registry.register(args.name, str(Path(args.path).resolve()), str(index_path))
        print(f"registered '{args.name}'")
        return 0
    if args.proj_cmd == "remove":
        registry.unregister(args.name)
        print(f"removed '{args.name}'")
        return 0
    if args.proj_cmd == "prune":
        dead = registry.prune(dry_run=args.dry_run)
        if not dead:
            print("no dangling entries")
            return 0
        verb = "would remove" if args.dry_run else "removed"
        for name in dead:
            print(f"{verb} '{name}' (index file gone)")
        return 0
    projects = registry.list_projects()
    if not projects:
        print("no projects registered")
        return 0
    for name, entry in sorted(projects.items()):
        print(f"{name}: {entry['root']} (indexed {entry.get('last_indexed', '?')})")
    return 0


def cmd_generate(args) -> int:
    from spindlebox.generate import BACKENDS, GenOptions
    backend_cls = BACKENDS.get(args.lang)
    if backend_cls is None:
        raise CliError(f"no generator backend for '{args.lang}' (have: {sorted(BACKENDS)})")
    idx, _root = _load_project(args)
    out_dir = Path(args.out or f"generated_{args.lang}")
    files = backend_cls().generate(idx, GenOptions(group=args.group, pretty=args.pretty))
    for f in files:
        target = out_dir / f.relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f.content)
        print(f"wrote {target}")
    return 0


def cmd_report(args) -> int:
    from spindlebox import reporting
    stacks = reporting.all_stacks()
    if args.list or not args.name:
        for name, stack in stacks.items():
            errs = reporting.check_stack(stack)
            state = "ok" if not errs else f"INVALID: {errs[0]}"
            print(f"{name:20s} {stack.get('description', ''):55s} [{state}]")
        return 0
    stack = stacks.get(args.name)
    if stack is None:
        raise CliError(f"no report '{args.name}' (have: {', '.join(stacks)})")
    if args.check:
        errs = reporting.check_stack(stack)
        for e in errs:
            print(f"error: {e}")
        return 1 if errs else 0
    overrides = json.loads(args.ctx) if args.ctx else {}
    if args.project:
        overrides["project"] = args.project
    if args.format:
        overrides["format"] = args.format
    ctx = reporting.run_stack(stack, overrides)
    if args.out:
        Path(args.out).write_text(ctx["output"])
        print(f"wrote {args.out}")
    else:
        print(ctx["output"], end="")
    return 0


def cmd_gaps(args) -> int:
    from spindlebox.gaps import find_gaps
    idx, _root = _load_project(args)
    gaps = find_gaps(idx)
    if args.kind:
        gaps = [g for g in gaps if g["kind"] == args.kind]
    if args.min_severity:
        order = {"high": 0, "medium": 1, "low": 2}
        cutoff = order[args.min_severity]
        gaps = [g for g in gaps if order.get(g["severity"], 3) <= cutoff]
    if args.json:
        print(json.dumps(gaps, indent=1))
        return 0
    if not gaps:
        print("no gaps found")
        return 0
    for g in gaps:
        loc = g.get("address") or ", ".join(g.get("members", []))
        print(f"[{g['severity']:>6}] {g['kind']:<20} {loc}  — {g['detail']}")
    return 0


def cmd_workflows(args) -> int:
    from spindlebox.workflows import mine_workflows
    idx, _root = _load_project(args)
    flows = mine_workflows(idx, min_confidence=args.min_confidence)
    if args.json:
        print(json.dumps(flows, indent=1))
        return 0
    if not flows:
        print("no candidate workflows found")
        return 0
    for f in flows[: args.limit]:
        chain = " → ".join(f["addresses"])
        print(f"[conf {f['confidence']:.2f} str {f['strength']:.2f}] "
              f"({f['stages']} stages) {chain}")
    return 0


def cmd_plugins(args) -> int:
    """What extends this spindlebox, and what tried to and could not."""
    from spindlebox import plugins

    found = plugins.loaded()
    for name, plugin in sorted(found.items()):
        stacks = sorted(k for k in plugins.stacks() if k.startswith(f"{name}:"))
        detail = f"api {plugin.api}"
        if stacks:
            detail += f", reports: {', '.join(stacks)}"
        print(f"{name:20s} {detail}")
    for name, why in plugins.problems():
        print(f"{name:20s} NOT LOADED: {why}")
    if not found and not plugins.problems():
        print("no plugins installed")
    return 0


def cmd_install_skill(args) -> int:
    src = Path(__file__).resolve().parent.parent / "skill" / "SKILL.md"
    if not src.exists():
        raise CliError(f"skill source not found at {src}")
    dest = Path.home() / ".claude" / "skills" / "spindlebox" / "SKILL.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(src.read_text())
    print(f"installed skill → {dest}")
    return 0


# ------------------------------------------------------------ parser

def _add_project_arg(p):
    p.add_argument("--project", help="registered project name (default: index at/above cwd)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spindlebox",
        description="Serialized Code Architecture indexer: build, query, validate, "
        "invoke, and generate from a function index.",
    )
    parser.add_argument("--version", action="version", version=spindlebox.__version__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("index", help="build/refresh the SCA index for a repo")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--name", help="project name (default: directory name)")
    p.add_argument("--langs", help="comma-separated: python,javascript,typescript,go,rust,bash")
    p.add_argument("--strict", action="store_true", help="'any'-typed signatures are errors")
    p.add_argument("--no-register", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--with-source", action="store_true",
                   help="store each item's body text (needed for body translation)")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("show", help="show items by ordinal range, address, or group path")
    p.add_argument("selector", nargs="?", help="'12-40,55' | address | group path")
    _add_project_arg(p)
    p.add_argument("--group")
    p.add_argument("--sig-class", dest="sig_class")
    p.add_argument("--lang")
    p.add_argument("--name", help="glob on item name")
    p.add_argument("--state-capture", dest="state_capture")
    p.add_argument("--deps", action="store_true")
    p.add_argument("--full", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--span", action="store_true",
                   help="print 'file<TAB>start<TAB>end<TAB>address' for a targeted read")
    p.add_argument("--fail-on-stale", dest="fail_on_stale", action="store_true",
                   help="exit non-zero if a shown item's file changed since indexing")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("search", help="search items (the anti-bloat check)")
    p.add_argument("query")
    _add_project_arg(p)
    p.add_argument("--all-projects", action="store_true", dest="all_projects")
    p.add_argument("--sig-class", dest="sig_class")
    p.add_argument("--lang")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--no-tests", action="store_true", dest="no_tests",
                   help="exclude test/spec items — anti-bloat wants product code")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("deps", help="dependencies and requirements for one item")
    p.add_argument("selector", help="ordinal or address")
    _add_project_arg(p)
    p.add_argument("--reverse", action="store_true", help="show callers instead")
    p.set_defaults(func=cmd_deps)

    p = sub.add_parser("stale", help="report whether the index still matches the tree")
    p.add_argument("path", nargs="?")
    _add_project_arg(p)
    p.add_argument("--check-new", action="store_true",
                   help="also walk the tree for files added since indexing (slower)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_stale)

    p = sub.add_parser("validate", help="compile-time validation pass over an index")
    p.add_argument("path", nargs="?")
    _add_project_arg(p)
    p.add_argument("--strict", action="store_true")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("call", help="live-invoke a Python item with a ctx dict")
    p.add_argument("selector", help="ordinal or address")
    p.add_argument("--ctx", required=True, help="JSON object feeding the item's params")
    _add_project_arg(p)
    p.set_defaults(func=cmd_call)

    p = sub.add_parser("generate", help="generate skeleton code from the index")
    p.add_argument("--lang", required=True)
    p.add_argument("--out")
    p.add_argument("--group", help="restrict to one group path")
    p.add_argument("--pretty", action="store_true",
                   help="expand bodies onto multiple lines (default: one line per spindle)")
    _add_project_arg(p)
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("report", help="run a SPIndlestack report (list with --list)")
    p.add_argument("name", nargs="?", help="report name (omit to list)")
    p.add_argument("--list", action="store_true", help="list available reports")
    p.add_argument("--check", action="store_true", help="validate the stack, don't run")
    p.add_argument("--format", choices=["md", "csv", "html", "json"])
    p.add_argument("--project", help="restrict to one registered project")
    p.add_argument("--ctx", help="JSON ctx overrides")
    p.add_argument("--out", help="write output to a file instead of stdout")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("pipeline", help="define/check/run/list ordered pipelines")
    pipe_sub = p.add_subparsers(dest="pipe_cmd", required=True)
    d = pipe_sub.add_parser("define")
    d.add_argument("name")
    d.add_argument("stages", nargs="+", help="ordinals or addresses, in order")
    _add_project_arg(d)
    c = pipe_sub.add_parser("check")
    c.add_argument("name")
    _add_project_arg(c)
    r = pipe_sub.add_parser("run", help="execute a pipeline (Python stages), "
                                        "applying its data-flow edges")
    r.add_argument("name")
    r.add_argument("--ctx", required=True, help="JSON object seeding the context")
    _add_project_arg(r)
    ls = pipe_sub.add_parser("list")
    _add_project_arg(ls)
    p.set_defaults(func=cmd_pipeline)

    p = sub.add_parser("projects", help="manage the central project registry")
    # not required: bare `spindlebox projects` lists, rather than erroring
    proj_sub = p.add_subparsers(dest="proj_cmd", required=False)
    proj_sub.add_parser("list")
    a = proj_sub.add_parser("add")
    a.add_argument("name")
    a.add_argument("path")
    r = proj_sub.add_parser("remove")
    r.add_argument("name")
    pr = proj_sub.add_parser("prune", help="drop entries whose index file is gone")
    pr.add_argument("--dry-run", action="store_true", dest="dry_run")
    p.set_defaults(func=cmd_projects, proj_cmd=None, dry_run=False)

    p = sub.add_parser("gaps", help="find gaps in the software (dead items, unprovided ctx "
                       "keys, unresolvable calls, near-duplicates)")
    _add_project_arg(p)
    p.add_argument("--kind", choices=["dead_item", "unprovided_ctx_key",
                                      "unresolvable_call", "near_duplicate"])
    p.add_argument("--min-severity", choices=["high", "medium", "low"], dest="min_severity")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_gaps)

    p = sub.add_parser("workflows", help="mine candidate cross-function pipelines from the SPI")
    _add_project_arg(p)
    p.add_argument("--min-confidence", type=float, default=workflows.DEFAULT_MIN_CONFIDENCE,
                   dest="min_confidence")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_workflows)

    p = sub.add_parser("install-skill", help="install the spindlebox skill to ~/.claude/skills")
    p.set_defaults(func=cmd_install_skill)

    p = sub.add_parser("plugins", help="what extends this spindlebox")
    p.set_defaults(func=cmd_plugins)

    return parser


def _plugin_command(argv: list[str]) -> tuple[str, list[str]] | None:
    """A plugin's name used as a subcommand, or None.

    THE BUILT-IN COMMANDS ARE MATCHED FIRST and never reach discovery: they are
    what the read-narrowly rule and other projects' scripts call, and they must
    not pay for -- or be broken by -- somebody else's plugin import. Only an
    unrecognised first word is looked up, and only against metadata.
    """
    if not argv or argv[0].startswith("-"):
        return None
    from spindlebox import plugins

    if argv[0] in plugins.BUILTIN_COMMANDS:
        return None
    return (argv[0], argv[1:]) if argv[0] in plugins.names() else None


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    plugin = _plugin_command(argv)
    if plugin is not None:
        name, rest = plugin
        from spindlebox import plugins

        loaded = plugins.loaded().get(name)
        if loaded is None or loaded.cli is None:
            why = dict(plugins.problems()).get(name, "provides no subcommand")
            print(f"spindlebox: plugin {name!r} cannot run: {why}", file=sys.stderr)
            return 1
        return loaded.cli(rest)

    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (CliError, DispatchError, SchemaError, ValueError) as e:
        print(f"spindlebox: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
