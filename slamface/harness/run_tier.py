"""Run one tier of the corpus through the full stage pipeline; emit JSONL + score.

Usage (in container or locally):
    python -m slamface.harness.run_tier [--tier N] [--state DIR] [--app-root DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import spindlebox
from slamface.harness.scoring import score_run
from slamface.harness.stages import run_target

LOCK_PATH = Path(__file__).parent / "corpus.lock.json"


def load_lock() -> dict:
    return json.loads(LOCK_PATH.read_text())


def run_tier(tier: int, state_dir: Path, app_root: Path) -> dict:
    lock = load_lock()
    tier_cfg = lock["tiers"].get(str(tier))
    if tier_cfg is None:
        raise SystemExit(f"tier {tier} not defined in corpus.lock.json")
    profile = lock["weights_profiles"][tier_cfg["weights_profile"]]

    run_id = "r-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    logs_dir = state_dir / "logs"
    corpus_dir = state_dir / "corpus"
    logs_dir.mkdir(parents=True, exist_ok=True)
    corpus_dir.mkdir(parents=True, exist_ok=True)

    base = {
        "run_id": run_id,
        "tier": tier,
        "spindlebox_version": spindlebox.__version__,
        "host": platform.node(),
        "image_digest": os.environ.get("SLAMFACE_IMAGE_DIGEST", "local"),
    }
    all_records: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="slamface_gen_") as scratch:
        for target in tier_cfg["targets"]:
            for record in run_target(target, corpus_dir, app_root, Path(scratch)):
                record.update(base, ts=datetime.now().isoformat(timespec="seconds"),
                              repo=target["name"], commit=target.get("commit", "local"))
                all_records.append(record)

    run_log = logs_dir / f"run-{run_id}.jsonl"
    with run_log.open("w") as fh:
        for record in all_records:
            fh.write(json.dumps(record) + "\n")
    failures = [r for r in all_records if r.get("status") not in ("ok", "skip")]
    if failures:
        with (logs_dir / f"failures-{run_id}.jsonl").open("w") as fh:
            for record in failures:
                fh.write(json.dumps(record) + "\n")

    result = score_run(all_records, profile)
    result.update(
        run_id=run_id, tier=tier, threshold=tier_cfg["threshold"],
        green=result["score"] >= tier_cfg["threshold"] and not failures,
        stages=len(all_records), failures=len(failures),
        generated_at=datetime.now().isoformat(timespec="seconds"),
        spindlebox_version=spindlebox.__version__,
    )
    (state_dir / f"score-{run_id}.json").write_text(json.dumps(result, indent=1) + "\n")
    (state_dir / "score-latest.json").write_text(json.dumps(result, indent=1) + "\n")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", type=int,
                        default=int(os.environ.get("SLAMFACE_TIER", "0")))
    parser.add_argument("--state", default=os.environ.get("SLAMFACE_STATE", "/state"))
    parser.add_argument("--app-root", default=os.environ.get("SLAMFACE_APP_ROOT", "/app"))
    args = parser.parse_args(argv)
    result = run_tier(args.tier, Path(args.state), Path(args.app_root))
    print("SLAMFACE_RUN " + json.dumps(
        {k: result[k] for k in ("run_id", "tier", "score", "threshold", "green", "failures")}))
    return 0 if result["green"] else 1


if __name__ == "__main__":
    sys.exit(main())
