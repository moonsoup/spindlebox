"""Checkpoint report: score escalation across runs, tier progression, issue flow.

Presented to the user every 10th loop run; the loop does not continue past a
checkpoint until the user has reviewed this and said so.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from slamface.ops import common


def collect_scores(state_dir: Path) -> list[dict]:
    scores = []
    for path in sorted(state_dir.glob("score-r-*.json")):
        try:
            scores.append(json.loads(path.read_text()))
        except (OSError, json.JSONDecodeError):
            continue
    return scores


def issue_flow(gh_json_fn=common.gh_json) -> dict:
    issues = gh_json_fn(["issue", "list", "--label", "slamface", "--state", "all",
                         "--limit", "500", "--json", "number,title,state,createdAt,closedAt"])
    return {
        "total": len(issues),
        "open": [i["number"] for i in issues if i["state"].lower() == "open"],
        "closed": [i["number"] for i in issues if i["state"].lower() == "closed"],
    }


def render(scores: list[dict], issues: dict, loop_state: dict) -> str:
    lines = ["# slamface checkpoint report", ""]
    lines.append(f"Loop runs completed: {loop_state.get('run_count', 0)} | "
                 f"current tier: {loop_state.get('tier', 0)} | "
                 f"consecutive green: {loop_state.get('consecutive_green', 0)}")
    lines.append(f"Issues: {issues['total']} total — "
                 f"{len(issues['open'])} open {issues['open'] or ''}, "
                 f"{len(issues['closed'])} closed {issues['closed'] or ''}")
    lines.append("")
    lines.append("| run | tier | score | threshold | green | stages | failures |")
    lines.append("|---|---|---|---|---|---|---|")
    for s in scores[-20:]:
        lines.append(f"| {s.get('run_id')} | {s.get('tier')} | {s.get('score')} "
                     f"| {s.get('threshold')} | {'✅' if s.get('green') else '❌'} "
                     f"| {s.get('stages')} | {s.get('failures')} |")
    if len(scores) >= 2:
        first, last = scores[0], scores[-1]
        lines.append("")
        lines.append(f"Trend: {first.get('score')} (run 1) → {last.get('score')} "
                     f"(run {len(scores)}) across tiers "
                     f"{first.get('tier')}→{last.get('tier')}")
    lines.append("")
    lines.append("Decision needed: continue / adjust weights-thresholds / stop.")
    return "\n".join(lines)


_CSV_FIELDS = ["run_id", "tier", "score", "threshold", "green", "stages", "failures",
               "generated_at", "spindlebox_version"]


def render_csv(scores: list[dict]) -> str:
    """Spreadsheet export: one row per scored run, all runs (not just last 20)."""
    import csv
    import io
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for s in scores:
        writer.writerow(s)
    return buf.getvalue()


def render_html(scores: list[dict], issues: dict, loop_state: dict) -> str:
    """Self-contained printable page (browser print → PDF)."""
    rows = "\n".join(
        "<tr>" + "".join(f"<td>{s.get(f, '')}</td>" for f in _CSV_FIELDS) + "</tr>"
        for s in scores
    )
    head = "".join(f"<th>{f}</th>" for f in _CSV_FIELDS)
    return f"""<!doctype html>
<meta charset="utf-8">
<title>slamface checkpoint report</title>
<style>
body {{ font: 14px/1.5 -apple-system, system-ui, sans-serif; margin: 2rem; }}
table {{ border-collapse: collapse; }}
th, td {{ border: 1px solid #999; padding: 4px 10px; text-align: left; }}
th {{ background: #eee; }}
@media print {{ body {{ margin: 0; }} }}
</style>
<h1>slamface checkpoint report</h1>
<p>Loop runs: {loop_state.get("run_count", 0)} — current tier {loop_state.get("tier", 0)}
— consecutive green {loop_state.get("consecutive_green", 0)}<br>
Issues: {issues["total"]} total, {len(issues["open"])} open, {len(issues["closed"])} closed</p>
<table><tr>{head}</tr>
{rows}
</table>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-pull", action="store_true")
    parser.add_argument("--state-dir", help="override (testing)")
    parser.add_argument("--csv", help="also write all runs as CSV to this path")
    parser.add_argument("--html", help="also write a printable HTML report to this path")
    args = parser.parse_args(argv)
    if args.state_dir:
        state_dir = Path(args.state_dir)
    else:
        state_dir = common.pull_state() if not args.no_pull else common.LOCAL_STATE
    from slamface.ops.loop_once import load_loop_state
    scores = collect_scores(state_dir)
    issues = issue_flow()
    loop_state = load_loop_state()
    if args.csv:
        Path(args.csv).write_text(render_csv(scores))
        print(f"csv: {args.csv}", file=sys.stderr)
    if args.html:
        Path(args.html).write_text(render_html(scores, issues, loop_state))
        print(f"html: {args.html}", file=sys.stderr)
    print(render(scores, issues, loop_state))
    return 0


if __name__ == "__main__":
    sys.exit(main())
