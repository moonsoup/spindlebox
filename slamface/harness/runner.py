"""Container entrypoint: dumb periodic cycle. No AI, no credentials, no network calls
except corpus git clones. All intelligence lives on the local side.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

from slamface.harness.run_tier import run_tier


def _control(state_dir: Path) -> dict:
    path = state_dir / "control.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def main() -> None:
    state_dir = Path(os.environ.get("SLAMFACE_STATE", "/state"))
    app_root = Path(os.environ.get("SLAMFACE_APP_ROOT", "/app"))
    interval = int(os.environ.get("SLAMFACE_INTERVAL", "900"))
    heartbeat = state_dir / "logs" / "runner.jsonl"
    heartbeat.parent.mkdir(parents=True, exist_ok=True)
    while True:
        tier = int(_control(state_dir).get("tier", os.environ.get("SLAMFACE_TIER", "0")))
        started = datetime.now().isoformat(timespec="seconds")
        try:
            result = run_tier(tier, state_dir, app_root)
            beat = {"ts": started, "event": "cycle", "tier": tier,
                    "run_id": result["run_id"], "score": result["score"],
                    "green": result["green"], "failures": result["failures"]}
        except Exception as e:  # the runner itself must never die
            beat = {"ts": started, "event": "cycle_error", "tier": tier,
                    "error_class": type(e).__name__, "message": str(e)[:500]}
        with heartbeat.open("a") as fh:
            fh.write(json.dumps(beat) + "\n")
        if os.environ.get("SLAMFACE_ONESHOT") == "1":
            break
        time.sleep(interval)


if __name__ == "__main__":
    main()
