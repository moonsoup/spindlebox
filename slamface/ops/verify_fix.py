"""Close an issue ONLY with fresh container evidence — the single allowed close path.

Protocol: deploy parity is asserted first (VPS runs origin/main), then the issue's
embedded repro command is executed --runs times (default 3) in the deployed container.
All runs must exit 0 → close with commit hash + image digest + verbatim outputs.
Any failure → label state:fix-failed-verify and comment the evidence instead.
"""

from __future__ import annotations

import argparse
import json
import re
import sys

from slamface.ops import common

_MARKER = re.compile(r"<!-- slamface-repro cwd=(\".*?\") cmd=(\".*?\") -->")


def extract_repro(issue_body: str) -> tuple[str, str] | None:
    m = _MARKER.search(issue_body)
    if not m:
        return None
    return json.loads(m.group(2)), json.loads(m.group(1))


def verify(issue_number: int, runs: int = 3,
           exec_fn=common.container_exec, gh_json_fn=common.gh_json,
           gh_fn=common.gh_run, ssh_fn=common.ssh,
           vps_head_fn=common.vps_head, origin_head_fn=common.origin_main_head) -> dict:
    issue = gh_json_fn(["issue", "view", str(issue_number), "--json", "body,title,state"])
    repro = extract_repro(issue["body"])
    if repro is None:
        return {"issue": issue_number, "verified": False,
                "reason": "no slamface-repro marker in issue body — cannot verify mechanically"}

    vps = vps_head_fn()
    origin = origin_head_fn()
    if vps != origin:
        return {"issue": issue_number, "verified": False,
                "reason": f"deploy pending: VPS at {vps[:12]}, origin/main at {origin[:12]}"}

    cmd, cwd = repro
    outputs = []
    for i in range(runs):
        proc = exec_fn(cmd, workdir=cwd or None)
        outputs.append(f"run {i + 1}: exit {proc.returncode}\n"
                       + (proc.stdout + proc.stderr).strip()[-400:])
        if proc.returncode != 0:
            gh_fn(["issue", "edit", str(issue_number), "--add-label", "state:fix-failed-verify"])
            gh_fn(["issue", "comment", str(issue_number), "--body",
                   f"Verification FAILED on run {i + 1}/{runs} at commit {vps}:\n```\n"
                   + "\n\n".join(outputs)[-2000:] + "\n```"])
            return {"issue": issue_number, "verified": False,
                    "reason": f"repro still failing (run {i + 1}/{runs})"}

    digest_proc = ssh_fn(f"docker inspect {common.CONTAINER} --format '{{{{.Image}}}}'")
    digest = digest_proc.stdout.strip()
    gh_fn(["issue", "close", str(issue_number), "--comment",
           f"## Verified fixed — closing with fresh-container evidence\n\n"
           f"- commit: {vps}\n- image: `{digest}`\n- repro executed {runs}×, all exit 0:\n"
           f"```\n" + "\n\n".join(outputs)[-2000:] + "\n```"])
    return {"issue": issue_number, "verified": True, "commit": vps, "image": digest}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args(argv)
    result = verify(args.issue, runs=args.runs)
    print(json.dumps(result, indent=1))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    sys.exit(main())
