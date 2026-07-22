"""Thin transport layer for the local ops scripts: SSH to the VPS, container exec,
state pull, and gh CLI. Everything above this module is pure logic and testable
with these callables mocked.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

VPS_IP = os.environ.get("SLAMFACE_VPS_IP", "2.25.209.57")
ROOT_KEY = os.path.expanduser(os.environ.get("SLAMFACE_ROOT_KEY", "~/.ssh/ies_hostinger_key"))
REPO = "moonsoup/spindlebox"
CONTAINER = "slamface_spindlebox"
VPS_REPO_DIR = "/opt/ies-platform/customers/slamface_spindlebox/repo"
LOCAL_STATE = Path(__file__).resolve().parents[1] / ".local" / "state"


def ssh(command: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["ssh", "-i", ROOT_KEY, "-o", "StrictHostKeyChecking=accept-new",
         "-o", "ConnectTimeout=15", f"root@{VPS_IP}", command],
        capture_output=True, text=True, timeout=timeout,
    )


def container_exec(command: str, timeout: int = 900, workdir: str | None = None) -> subprocess.CompletedProcess:
    # docker exec -w requires an ABSOLUTE path; a relative workdir crashes with
    # "Cwd must be an absolute path" (exit 128). Only pass -w when absolute;
    # otherwise fold it into the command so it still runs.
    if workdir and workdir.startswith("/"):
        wd = f"-w {workdir} "
    elif workdir:
        command = f"cd {workdir} && {command}"
        wd = ""
    else:
        wd = ""
    return ssh(f"docker exec {wd}{CONTAINER} sh -c {json.dumps(command)}", timeout=timeout)


# exit codes / markers that mean "the harness could not run the repro", NOT
# "the repro reproduced the failure" — must never be read as a reproduction.
def is_infra_error(proc: subprocess.CompletedProcess) -> bool:
    blob = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 128 or "OCI runtime exec failed" in blob \
        or "Cwd must be an absolute path" in blob or "No such container" in blob


def pull_state(local_dir: Path | None = None) -> Path:
    """Copy /state (logs + scores) from the container volume to the local mirror."""
    local_dir = local_dir or LOCAL_STATE
    local_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["ssh", "-i", ROOT_KEY, "-o", "StrictHostKeyChecking=accept-new",
         f"root@{VPS_IP}",
         f"docker exec {CONTAINER} tar -C /state -cf - logs $(docker exec {CONTAINER} sh -c 'ls /state/score-*.json 2>/dev/null | xargs -n1 basename' | tr '\\n' ' ')"],
        capture_output=True, timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"state pull failed: {proc.stderr.decode()[-300:]}")
    subprocess.run(["tar", "-xf", "-", "-C", str(local_dir)], input=proc.stdout, check=True)
    return local_dir


def gh_json(args: list[str], timeout: int = 60) -> list | dict:
    proc = subprocess.run(["gh", *args, "--repo", REPO], capture_output=True, text=True,
                          timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])} failed: {proc.stderr[-300:]}")
    return json.loads(proc.stdout) if proc.stdout.strip() else []


def gh_run(args: list[str], timeout: int = 60) -> str:
    proc = subprocess.run(["gh", *args, "--repo", REPO], capture_output=True, text=True,
                          timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])} failed: {proc.stderr[-300:]}")
    return proc.stdout


def vps_head() -> str:
    # the repo is owned by the deploy user; read it as that user (git ownership guard)
    proc = ssh(f"sudo -u deploy git -C {VPS_REPO_DIR} rev-parse HEAD")
    if proc.returncode != 0:
        raise RuntimeError(f"cannot read VPS HEAD: {proc.stderr[-200:]}")
    return proc.stdout.strip()


def origin_main_head() -> str:
    proc = subprocess.run(["git", "ls-remote", "origin", "refs/heads/main"],
                          capture_output=True, text=True, timeout=60,
                          cwd=Path(__file__).resolve().parents[2])
    if proc.returncode != 0:
        raise RuntimeError(f"git ls-remote failed: {proc.stderr[-200:]}")
    return proc.stdout.split()[0]
