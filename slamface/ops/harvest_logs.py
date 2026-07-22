"""Harvest container failure logs, group by error signature, diff against GitHub issues.

Output categories:
- new:       signature never seen in any slamface issue → candidate for filing
- recurring: signature matches an OPEN slamface issue → comment, never a new issue
- regressed: signature matches a CLOSED slamface issue → reopen with evidence
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from slamface.ops import common

_SIG_IN_TITLE = re.compile(r"\[slamface:([0-9a-f]{12})\]")


def parse_failures(logs_dir: Path) -> dict[str, dict]:
    """Group failure records from all failures-*.jsonl by error signature."""
    groups: dict[str, dict] = {}
    for path in sorted(logs_dir.glob("failures-*.jsonl")):
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            error = record.get("error") or {}
            sig = error.get("signature")
            if not sig:
                continue
            group = groups.setdefault(sig, {
                "signature": sig,
                "stage": record.get("stage"),
                "error_class": error.get("class"),
                "trace_head": error.get("trace_head"),
                "tier": record.get("tier"),
                "repos": [],
                "run_ids": [],
                "count": 0,
                "sample": None,
            })
            group["count"] += 1
            if record.get("repo") not in group["repos"]:
                group["repos"].append(record.get("repo"))
            if record.get("run_id") not in group["run_ids"]:
                group["run_ids"].append(record.get("run_id"))
            if group["sample"] is None or len(error.get("log_excerpt", "")) > len(
                (group["sample"].get("error") or {}).get("log_excerpt", "")
            ):
                group["sample"] = record
    return groups


def issue_signatures(issues: list[dict]) -> dict[str, dict]:
    """Map signature → {number, state} from gh issue list JSON."""
    out: dict[str, dict] = {}
    for issue in issues:
        m = _SIG_IN_TITLE.search(issue.get("title", ""))
        if m:
            out[m.group(1)] = {"number": issue["number"],
                               "state": issue.get("state", "").lower()}
    return out


def harvest(logs_dir: Path, issues: list[dict], since_run: str | None = None) -> dict:
    groups = parse_failures(logs_dir)
    if since_run:
        groups = {s: g for s, g in groups.items()
                  if any(r > since_run for r in g["run_ids"])}
    known = issue_signatures(issues)
    result = {"new": [], "recurring": [], "regressed": []}
    for sig, group in sorted(groups.items()):
        info = known.get(sig)
        if info is None:
            result["new"].append(group)
        elif info["state"] == "open":
            result["recurring"].append({**group, "issue": info["number"]})
        else:
            result["regressed"].append({**group, "issue": info["number"]})
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-pull", action="store_true",
                        help="use the existing local state mirror")
    parser.add_argument("--since-run", help="only failures from runs after this run_id")
    parser.add_argument("--logs-dir", help="override logs dir (testing)")
    args = parser.parse_args(argv)

    if args.logs_dir:
        logs_dir = Path(args.logs_dir)
    else:
        state = common.pull_state() if not args.no_pull else common.LOCAL_STATE
        logs_dir = state / "logs"
    issues = common.gh_json([
        "issue", "list", "--label", "slamface", "--state", "all",
        "--limit", "500", "--json", "number,title,state",
    ])
    result = harvest(logs_dir, issues, args.since_run)
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
