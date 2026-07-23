#!/bin/bash
# Manual deploy fallback + rollback. Mirrors the CI path (runs the same forced-command
# script as the deploy user). Usage: deploy.sh [--rollback]
set -euo pipefail
ENV_OPS="$(cd "$(dirname "$0")/.." && pwd)/.env.ops"
[ -f "$ENV_OPS" ] && . "$ENV_OPS"
VPS_IP="${VPS_IP:?VPS_IP not set — create slamface/.env.ops (gitignored) or export VPS_IP}"
ROOT_KEY="${ROOT_KEY:-$HOME/.ssh/ies_hostinger_key}"
SSH=(ssh -i "$ROOT_KEY" -o StrictHostKeyChecking=accept-new "root@$VPS_IP")

if [[ "${1:-}" == "--rollback" ]]; then
  "${SSH[@]}" bash -s << 'REMOTE'
set -euo pipefail
last_good=$(cat /home/deploy/slamface_last_good)
[[ "$last_good" != "none" ]] || { echo "no last_good recorded"; exit 1; }
cd /opt/ies-platform/customers/slamface_spindlebox/repo
sudo -u deploy git reset --hard "$last_good"
sudo -u deploy docker compose -f slamface/compose.yaml build --quiet
sudo -u deploy docker compose -f slamface/compose.yaml up -d
echo "ROLLED BACK to $last_good"
REMOTE
else
  "${SSH[@]}" sudo -u deploy /usr/local/bin/slamface-deploy
fi
