"""File/annotate GitHub issues from harvest output — with mechanical reproduction first.

Rules enforced here:
- an issue is only FILED after the failing command re-executes and fails again in the
  container (fresh reproduction, not just a log line); if it passes on re-run it is
  reported as flaky instead
- at most --max-new new issues per pass (anti-spam); the rest are listed as deferred
- recurring signatures get a count comment on their open issue, never a duplicate
- regressed signatures reopen their closed issue with the new evidence
- a machine-readable repro marker is embedded for verify_fix.py
"""

from __future__ import annotations

import argparse
import json
import sys

from slamface.ops import common

LABELS = ("slamface", "state:reproduced")
_LABEL_DEFS = {
    "slamface": ("b60205", "filed by the slamface hardening loop"),
    "state:reproduced": ("fbca04", "failure mechanically reproduced in container"),
    "state:fix-failed-verify": ("d93f0b", "a fix landed but verification failed"),
}


def ensure_labels(tier: int, gh_fn=common.gh_run) -> None:
    """Idempotently create the labels the loop uses (gh errors on dupes are ignored)."""
    defs = dict(_LABEL_DEFS)
    defs[f"tier-{tier}"] = ("0e8a16", f"found at corpus tier {tier}")
    for name, (color, desc) in defs.items():
        try:
            gh_fn(["label", "create", name, "--color", color, "--description", desc])
        except RuntimeError:
            pass  # already exists


def repro_marker(cmd: str, cwd: str) -> str:
    return f"<!-- slamface-repro cwd={json.dumps(cwd)} cmd={json.dumps(cmd)} -->"


def build_body(group: dict, repro_output: str, analysis: str | None) -> str:
    sample = group["sample"] or {}
    error = sample.get("error") or {}
    cmd = sample.get("repro_cmd") or sample.get("cmd", "")
    cwd = ""  # repro_cmd embeds its own cd; marker cwd kept for schema stability
    hypothesis = analysis or "*(analysis pending — hypothesis to be added before fixing)*"
    return f"""## Evidence (slamface tier {group.get('tier')}, stage `{group['stage']}`)

- error: `{group['error_class']}` at `{group['trace_head']}`
- occurrences: {group['count']} across runs {', '.join(group['run_ids'][-5:])}
- corpus repos affected: {', '.join(group['repos'])}

Original failure excerpt:
```
{error.get('log_excerpt', '')[-1500:]}
```

## Fresh reproduction (container, this pass)
```
$ {cmd}
{repro_output[-1500:]}
```

## Hypothesis
{hypothesis}

{repro_marker(cmd, str(cwd))}
signature: `{group['signature']}`
"""


def reproduce_in_container(group: dict, exec_fn=common.container_exec) -> tuple[bool, str]:
    """Re-run the standalone repro command; True = still fails (reproduced).

    Requires a self-contained repro_cmd. A bare stage `cmd` is NOT used as a
    fallback: it may lack its working directory and fail for the wrong reason
    (drill finding: bare `cargo check` fails anywhere with no crate, producing
    false reproductions that wrongly reopened fixed issues)."""
    sample = group["sample"] or {}
    cmd = sample.get("repro_cmd")
    if not cmd:
        return False, "(no standalone repro_cmd recorded — cannot reproduce)"
    proc = exec_fn(cmd)
    output = (proc.stdout + "\n" + proc.stderr).strip()
    return proc.returncode != 0, output


def process(harvest_result: dict, tier: int, max_new: int = 5,
            analysis_map: dict[str, str] | None = None,
            exec_fn=common.container_exec, gh_fn=common.gh_run) -> dict:
    analysis_map = analysis_map or {}
    outcome = {"filed": [], "flaky": [], "commented": [], "reopened": [], "deferred": []}
    if harvest_result.get("new"):
        ensure_labels(tier, gh_fn)

    for group in harvest_result.get("recurring", []):
        gh_fn(["issue", "comment", str(group["issue"]), "--body",
               f"Seen again: {group['count']} occurrence(s), latest run "
               f"{group['run_ids'][-1]} (signature `{group['signature']}`)."])
        outcome["commented"].append(group["issue"])

    for group in harvest_result.get("regressed", []):
        reproduced, output = reproduce_in_container(group, exec_fn)
        if not reproduced:
            outcome["flaky"].append(group["signature"])
            continue
        gh_fn(["issue", "reopen", str(group["issue"])])
        gh_fn(["issue", "comment", str(group["issue"]), "--body",
               "REGRESSION — signature reappeared after close. Fresh repro:\n```\n"
               + output[-1500:] + "\n```"])
        outcome["reopened"].append(group["issue"])

    new = harvest_result.get("new", [])
    for group in new[:max_new]:
        reproduced, output = reproduce_in_container(group, exec_fn)
        if not reproduced:
            outcome["flaky"].append(group["signature"])
            continue
        title = (f"[slamface:{group['signature']}] {group['error_class']} "
                 f"in {group['trace_head']}")[:200]
        body = build_body(group, output, analysis_map.get(group["signature"]))
        gh_fn(["issue", "create", "--title", title, "--body", body,
               "--label", ",".join(LABELS + (f"tier-{tier}",))])
        outcome["filed"].append(group["signature"])
    for group in new[max_new:]:
        outcome["deferred"].append(group["signature"])
    return outcome


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--harvest", default="-",
                        help="harvest JSON file, or - for stdin")
    parser.add_argument("--tier", type=int, required=True)
    parser.add_argument("--max-new", type=int, default=5)
    parser.add_argument("--analysis", help="JSON file: {signature: hypothesis markdown}")
    args = parser.parse_args(argv)
    raw = sys.stdin.read() if args.harvest == "-" else open(args.harvest).read()
    analysis = json.load(open(args.analysis)) if args.analysis else {}
    outcome = process(json.loads(raw), tier=args.tier, max_new=args.max_new,
                      analysis_map=analysis)
    print(json.dumps(outcome, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
