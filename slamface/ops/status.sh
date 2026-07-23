#!/bin/bash
# Show slamface container status, latest score, and recent heartbeats. Read-only.
set -euo pipefail
ENV_OPS="$(cd "$(dirname "$0")/.." && pwd)/.env.ops"
[ -f "$ENV_OPS" ] && . "$ENV_OPS"
VPS_IP="${VPS_IP:?VPS_IP not set — create slamface/.env.ops (gitignored) or export VPS_IP}"
ROOT_KEY="${ROOT_KEY:-$HOME/.ssh/ies_hostinger_key}"
SSH=(ssh -i "$ROOT_KEY" -o StrictHostKeyChecking=accept-new "root@$VPS_IP")

echo "== container =="
"${SSH[@]}" "docker ps --filter name=slamface_spindlebox --format '{{.Names}}  {{.Status}}  {{.Image}}'"
echo "== latest score =="
"${SSH[@]}" "docker exec slamface_spindlebox cat /state/score-latest.json" 2>/dev/null \
  || echo "(no score yet)"
echo "== last heartbeats =="
"${SSH[@]}" "docker exec slamface_spindlebox tail -n 5 /state/logs/runner.jsonl" 2>/dev/null \
  || echo "(no heartbeats yet)"
echo "== deployed commit =="
"${SSH[@]}" "sudo -u deploy git -C /opt/ies-platform/customers/slamface_spindlebox/repo rev-parse HEAD"
