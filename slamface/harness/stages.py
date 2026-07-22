"""Deterministic harness stages: every stage is a subprocess with a timeout,
captured output, and a structured record. No stage assumes prior state.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from slamface.harness.signatures import error_signature

STAGE_TIMEOUT = 600  # seconds, per stage
_TB_FILE = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')
_TB_CLASS = re.compile(r"^(\w+(?:\.\w+)*(?:Error|Exception|Interrupt|Exit))\b:?\s*(.*)$", re.M)
_ITEMS = re.compile(r"indexed \S+: (\d+) items, (\d+) signature classes")
_RUSTC_ERR = re.compile(r"error\[(E\d+)\][^\n]*\n\s*-->\s*([^:\n]+)")


def _fail_trace_head(stage: str, output: str) -> str:
    """Failure-mode identity for non-traceback failures. For cargo, the first rustc
    error code + file makes distinct compile errors distinct signatures
    (drill finding: '<stage> exit' collapsed unrelated cargo failures)."""
    m = _RUSTC_ERR.search(output)
    if m:
        return f"{stage} {m.group(1)} {m.group(2).strip()}"
    return f"{stage} exit"


def parse_traceback(stderr: str) -> dict | None:
    """Extract {class, message, trace_head} from a Python traceback, else None."""
    if "Traceback (most recent call last)" not in stderr:
        return None
    files = _TB_FILE.findall(stderr)
    classes = _TB_CLASS.findall(stderr)
    if not classes:
        return None
    cls, msg = classes[-1]
    trace_head = f"{files[-1][0]}:{files[-1][1]} in {files[-1][2]}" if files else "unknown"
    return {"class": cls, "message": msg.strip()[:500], "trace_head": trace_head}


def run_stage(
    stage: str,
    cmd: list[str],
    cwd: Path,
    lang: str,
    timeout: int = STAGE_TIMEOUT,
    expect_exit: tuple[int, ...] = (0,),
    repro_cmd: str | None = None,
) -> dict:
    """repro_cmd: standalone shell command (stable paths, cd included) that reproduces
    this stage outside the run — this is what issues embed and verify_fix executes."""
    started = time.time()
    record: dict = {"stage": stage, "lang": lang, "cmd": " ".join(cmd),
                    "cwd": str(cwd),
                    "repro_cmd": repro_cmd or f"cd {cwd} && {' '.join(cmd)}"}
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        duration = int((time.time() - started) * 1000)
        tb = parse_traceback(proc.stderr)
        record.update(duration_ms=duration, exit_code=proc.returncode)
        if tb is not None:
            record["status"] = "error"
            record["error"] = {
                **tb,
                "log_excerpt": proc.stderr[-4000:],
                "signature": error_signature(stage, tb["class"], tb["trace_head"], lang),
            }
        elif proc.returncode in expect_exit:
            record["status"] = "ok"
            record["stdout_tail"] = proc.stdout[-500:]
            m = _ITEMS.search(proc.stdout)
            if m:
                record["metrics"] = {"items": int(m.group(1)), "sig_classes": int(m.group(2))}
        else:
            record["status"] = "fail"
            trace_head = _fail_trace_head(stage, proc.stderr or proc.stdout)
            record["error"] = {
                "class": "NonzeroExit",
                "message": f"exit {proc.returncode}, expected {expect_exit}",
                "trace_head": trace_head,
                "log_excerpt": (proc.stderr or proc.stdout)[-4000:],
                "signature": error_signature(stage, "NonzeroExit", trace_head, lang),
            }
    except subprocess.TimeoutExpired:
        record.update(
            status="timeout", duration_ms=int((time.time() - started) * 1000), exit_code=None,
            error={
                "class": "Timeout", "message": f"stage exceeded {timeout}s",
                "trace_head": f"{stage} timeout", "log_excerpt": "",
                "signature": error_signature(stage, "Timeout", f"{stage} timeout", lang),
            },
        )
    return record


def spindlebox_cmd(*args: str) -> list[str]:
    return [sys.executable, "-m", "spindlebox", *args]


def stage_fetch(target: dict, corpus_dir: Path, app_root: Path) -> tuple[dict, Path | None]:
    """Resolve a corpus target to a local directory (clone+pin if remote)."""
    lang = target.get("lang", "multi")
    if "path" in target:
        repo_dir = Path(target["path"].replace("{app}", str(app_root)))
        status = "ok" if repo_dir.is_dir() else "fail"
        record = {"stage": "fetch", "lang": lang, "status": status,
                  "duration_ms": 0, "exit_code": 0 if status == "ok" else 1}
        if status == "fail":
            record["error"] = {
                "class": "MissingPath", "message": str(repo_dir),
                "trace_head": "fetch missing_path", "log_excerpt": "",
                "signature": error_signature("fetch", "MissingPath", "fetch missing_path", lang),
            }
            return record, None
        return record, repo_dir
    repo_dir = corpus_dir / target["name"]
    if (repo_dir / ".git").exists():
        rec = run_stage("fetch", ["git", "-C", str(repo_dir), "checkout", "-q",
                                  target["commit"]], repo_dir, lang)
        return rec, (repo_dir if rec["status"] == "ok" else None)
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    clone = run_stage("fetch", ["git", "clone", "--quiet", target["url"], str(repo_dir)],
                      corpus_dir, lang, timeout=1200)
    if clone["status"] != "ok":
        return clone, None
    pin = run_stage("fetch", ["git", "-C", str(repo_dir), "checkout", "-q", target["commit"]],
                    repo_dir, lang)
    return pin, (repo_dir if pin["status"] == "ok" else None)


def run_target(target: dict, corpus_dir: Path, app_root: Path, scratch: Path) -> list[dict]:
    """Run the full stage pipeline for one corpus target."""
    records: list[dict] = []
    fetch_rec, repo_dir = stage_fetch(target, corpus_dir, app_root)
    records.append(fetch_rec)
    if repo_dir is None:
        return records
    lang = target.get("lang", "multi")

    records.append(run_stage(
        "index", spindlebox_cmd("index", str(repo_dir), "--no-register",
                                "--name", f"slamface_{target['name']}"),
        repo_dir, lang))

    expect = (0,) if target.get("expect_validate", "clean") == "clean" else (0, 1)
    records.append(run_stage(
        "validate", spindlebox_cmd("validate", str(repo_dir)), repo_dir, lang,
        expect_exit=expect))

    records.append(run_stage(
        "show_smoke", spindlebox_cmd("show", "0-5"), repo_dir, lang))

    gen_dir = scratch / f"gen_{target['name']}"
    # standalone repro chain with stable paths (scratch dirs are ephemeral).
    # Re-index first so index-time fixes (normalization, sig classes) are actually
    # exercised — generating against a stale .spi would test the old index.
    regen = (f"cd {repo_dir} && python3 -m spindlebox index . --no-register >/dev/null && "
             f"python3 -m spindlebox generate --lang rust --out /tmp/repro_{target['name']}")
    gen_rec = run_stage(
        "generate_rust", spindlebox_cmd("generate", "--lang", "rust", "--out", str(gen_dir)),
        repo_dir, lang, repro_cmd=regen)
    records.append(gen_rec)

    if gen_rec["status"] == "ok":
        if shutil.which("cargo"):
            records.append(run_stage(
                "cargo_check", ["cargo", "check", "--quiet"], gen_dir, lang, timeout=900,
                repro_cmd=f"{regen} && cd /tmp/repro_{target['name']} && cargo check --quiet"))
        else:
            records.append({"stage": "cargo_check", "lang": lang, "status": "skip",
                            "duration_ms": 0, "exit_code": None,
                            "detail": "cargo not installed"})

    if target.get("probes"):
        for probe, args in (("gaps_probe", ["gaps", "--json"]),
                            ("workflows_probe", ["workflows", "--json"])):
            rec = run_stage(probe, spindlebox_cmd(*args), repo_dir, lang,
                            repro_cmd=f"cd {repo_dir} && python3 -m spindlebox {args[0]} --json")
            records.append(rec)

    if target.get("dispatch"):
        rec = run_stage(
            "dispatch", spindlebox_cmd("call", "pure.add", "--ctx", '{"a": 2, "b": 40}'),
            repo_dir, lang)
        if rec["status"] == "ok" and '"add_result": 42' not in rec.get("stdout_tail", ""):
            rec["status"] = "fail"
            rec["error"] = {
                "class": "WrongOutput", "message": "add_result != 42",
                "trace_head": "dispatch wrong_output",
                "log_excerpt": rec.get("stdout_tail", ""),
                "signature": error_signature("dispatch", "WrongOutput",
                                             "dispatch wrong_output", lang),
            }
        records.append(rec)
    return records
