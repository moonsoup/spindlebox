"""One outer-loop iteration. Machine-readable status; /loop- and dogfooder-compatible.

Sequence: deploy parity → fresh tier run in container → pull state → harvest →
file/annotate issues (with mechanical reproduction) → auto-verify pending fixes →
score/promotion/checkpoint decision.

Hard rules encoded: every 10th run halts at a checkpoint for human review; promotion
needs 2 consecutive greens AND zero open slamface issues; nothing here ever closes
an issue except through verify_fix.verify().
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from slamface.harness.run_tier import LOCK_PATH
from slamface.ops import common, file_issues, harvest_logs, verify_fix

LOOP_STATE = common.LOCAL_STATE / "loop.json"
_RUN_LINE = re.compile(r"SLAMFACE_RUN (\{.*\})")
_SIG_IN_LOG = re.compile(r"slamface:([0-9a-f]{12})")


def load_loop_state() -> dict:
    if LOOP_STATE.exists():
        try:
            return json.loads(LOOP_STATE.read_text())
        except (OSError, json.JSONDecodeError):
            pass
    return {"run_count": 0, "consecutive_green": 0, "tier": 0, "last_run_id": None}


def save_loop_state(state: dict) -> None:
    LOOP_STATE.parent.mkdir(parents=True, exist_ok=True)
    LOOP_STATE.write_text(json.dumps(state, indent=1) + "\n")


def fixed_pending_signatures(gh_json_fn=common.gh_json) -> dict[str, int]:
    """Open slamface issues whose signature appears in a commit message on main."""
    issues = gh_json_fn(["issue", "list", "--label", "slamface", "--state", "open",
                         "--limit", "200", "--json", "number,title"])
    sig_to_issue = harvest_logs.issue_signatures(issues)
    log = subprocess.run(["git", "log", "--format=%H %s %b", "-100", "origin/main"],
                         capture_output=True, text=True,
                         cwd=Path(__file__).resolve().parents[2]).stdout
    mentioned = set(_SIG_IN_LOG.findall(log))
    return {sig: info["number"] for sig, info in sig_to_issue.items() if sig in mentioned}


def trigger_run(tier: int, exec_fn=common.container_exec) -> dict:
    proc = exec_fn(f"python -m slamface.harness.run_tier --tier {tier}", timeout=3600)
    m = _RUN_LINE.search(proc.stdout)
    if not m:
        raise RuntimeError(f"no SLAMFACE_RUN line in container output: "
                           f"{(proc.stdout + proc.stderr)[-400:]}")
    return json.loads(m.group(1))


def loop_once(tier: int | None = None, max_new: int = 5, deps=None) -> dict:
    """deps: injection point for tests — dict of the common/file/harvest/verify callables."""
    d = deps or {}
    vps_head = d.get("vps_head", common.vps_head)
    origin_head = d.get("origin_head", common.origin_main_head)
    exec_fn = d.get("exec_fn", common.container_exec)
    pull_state = d.get("pull_state", common.pull_state)
    gh_json_fn = d.get("gh_json", common.gh_json)
    gh_fn = d.get("gh_run", common.gh_run)
    verify_fn = d.get("verify", verify_fix.verify)

    state = load_loop_state()
    tier = tier if tier is not None else state.get("tier", 0)
    status: dict = {"tier": tier, "run_count": state["run_count"] + 1}

    vps, origin = vps_head(), origin_head()
    if vps != origin:
        status.update(next_action="deploy_pending",
                      detail=f"VPS {vps[:12]} != origin/main {origin[:12]}")
        print("SLAMFACE_STATUS " + json.dumps(status))
        return status

    run = trigger_run(tier, exec_fn)
    status.update(run_id=run["run_id"], score=run["score"], green=run["green"],
                  threshold=run["threshold"])

    state_dir = pull_state()
    issues = gh_json_fn(["issue", "list", "--label", "slamface", "--state", "all",
                         "--limit", "500", "--json", "number,title,state"])
    harvest = harvest_logs.harvest(state_dir / "logs", issues,
                                   since_run=state.get("last_run_id"))
    filing = file_issues.process(harvest, tier=tier, max_new=max_new,
                                 exec_fn=exec_fn, gh_fn=gh_fn)
    status["issues_new"] = len(filing["filed"])
    status["issues_flaky"] = len(filing["flaky"])

    verified = []
    for number in fixed_pending_signatures(gh_json_fn).values():
        result = verify_fn(number)
        verified.append({"issue": number, "verified": result["verified"]})
    status["issues_closed"] = sum(1 for v in verified if v["verified"])

    open_count = len([i for i in gh_json_fn(
        ["issue", "list", "--label", "slamface", "--state", "open",
         "--limit", "500", "--json", "number"])])
    status["issues_open"] = open_count

    state["run_count"] += 1
    state["last_run_id"] = run["run_id"]
    state["consecutive_green"] = (
        state.get("consecutive_green", 0) + 1 if run["green"] and open_count == 0 else 0
    )
    state["tier"] = tier
    status["consecutive_green"] = state["consecutive_green"]

    lock = json.loads(LOCK_PATH.read_text())
    if state["run_count"] % 10 == 0:
        status["next_action"] = "checkpoint"
    elif filing["filed"] or open_count:
        status["next_action"] = f"fix #{_lowest_open(gh_json_fn)}" if open_count else "triage"
    elif state["consecutive_green"] >= 2:
        next_tier = tier + 1
        if str(next_tier) in lock["tiers"]:
            status["next_action"] = "promote"
            status["next_tier"] = next_tier
        else:
            status["next_action"] = "escalate"
    else:
        status["next_action"] = "rerun"

    save_loop_state(state)
    print("SLAMFACE_STATUS " + json.dumps(status))
    return status


def _lowest_open(gh_json_fn) -> int:
    issues = gh_json_fn(["issue", "list", "--label", "slamface", "--state", "open",
                         "--limit", "500", "--json", "number"])
    return min(i["number"] for i in issues)


def promote(next_tier: int, ssh_fn=common.ssh) -> None:
    """Bump the container's tier via /state/control.json (picked up next cycle)."""
    control = json.dumps({"tier": next_tier})
    ssh_fn(f"docker exec {common.CONTAINER} sh -c "
           f"'echo {json.dumps(control)} > /state/control.json'")
    state = load_loop_state()
    state["tier"] = next_tier
    state["consecutive_green"] = 0
    save_loop_state(state)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", type=int)
    parser.add_argument("--max-new", type=int, default=5)
    parser.add_argument("--promote", type=int, help="set container tier and exit")
    args = parser.parse_args(argv)
    if args.promote is not None:
        promote(args.promote)
        print(f"promoted container to tier {args.promote}")
        return 0
    status = loop_once(tier=args.tier, max_new=args.max_new)
    return 0 if status.get("next_action") not in ("deploy_pending",) else 1


if __name__ == "__main__":
    sys.exit(main())
