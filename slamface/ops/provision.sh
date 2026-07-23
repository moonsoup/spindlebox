#!/bin/bash
# One-time VPS provisioning for slamface_spindlebox. Idempotent.
# Usage: provision.sh            # full provisioning (expects keys prepared, see below)
#        provision.sh --audit    # verify security posture only
#
# Prerequisites created by the caller BEFORE running (never printed to terminal):
#   ~/.ssh/slamface_ci_ed25519[.pub]   local CI keypair; private key → gh secret SLAMFACE_DEPLOY_KEY
set -euo pipefail

ENV_OPS="$(cd "$(dirname "$0")/.." && pwd)/.env.ops"
[ -f "$ENV_OPS" ] && . "$ENV_OPS"
VPS_IP="${VPS_IP:?VPS_IP not set — create slamface/.env.ops (gitignored) or export VPS_IP}"
ROOT_KEY="${ROOT_KEY:-$HOME/.ssh/ies_hostinger_key}"
CI_PUB="${CI_PUB:-$HOME/.ssh/slamface_ci_ed25519.pub}"
BASE=/opt/ies-platform/customers/slamface_spindlebox
SSH=(ssh -i "$ROOT_KEY" -o StrictHostKeyChecking=accept-new "root@$VPS_IP")

if [[ "${1:-}" == "--audit" ]]; then
  "${SSH[@]}" bash -s << 'AUDIT'
set -e
echo "== deploy user =="; id deploy
echo "== forced command =="; grep -o 'command="[^"]*"' /home/deploy/.ssh/authorized_keys
echo "== listening ports (slamface must expose none) =="
ss -tlnp | grep -v '127.0.0.1\|::1' | grep -i slamface || echo "OK: no public slamface ports"
echo "== container =="; docker ps --filter name=slamface_spindlebox --format '{{.Names}} {{.Status}}'
AUDIT
  exit 0
fi

[[ -f "$CI_PUB" ]] || { echo "missing $CI_PUB — generate the CI keypair first"; exit 1; }
CI_PUB_CONTENT=$(cat "$CI_PUB")

"${SSH[@]}" bash -s << REMOTE
set -euo pipefail
# 1. deploy user (docker group, no sudo)
id deploy &>/dev/null || useradd -m -s /bin/bash -G docker deploy

# 2. forced-command authorized_keys for the CI key
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
cat > /home/deploy/.ssh/authorized_keys << 'AK'
command="/usr/local/bin/slamface-deploy",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty ${CI_PUB_CONTENT}
AK
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys

# 3. read-only GitHub repo deploy key (generated on the VPS, private key never leaves it)
if [[ ! -f /home/deploy/.ssh/spindlebox_repo_ed25519 ]]; then
  sudo -u deploy ssh-keygen -t ed25519 -N '' -q \
    -f /home/deploy/.ssh/spindlebox_repo_ed25519 -C slamface-repo-readonly
fi

# 4. layout
install -d -o deploy -g deploy "$BASE"
REMOTE

# 5. register the VPS repo key as a read-only GitHub deploy key
VPS_REPO_PUB=$("${SSH[@]}" cat /home/deploy/.ssh/spindlebox_repo_ed25519.pub)
if ! gh repo deploy-key list --json title -q '.[].title' | grep -q '^slamface-vps$'; then
  echo "$VPS_REPO_PUB" | gh repo deploy-key add - --title slamface-vps
fi

# 6. install the forced-command deploy script + clone + first start
scp -i "$ROOT_KEY" -o StrictHostKeyChecking=accept-new \
  "$(dirname "$0")/slamface-deploy" "root@$VPS_IP:/usr/local/bin/slamface-deploy"
"${SSH[@]}" bash -s << REMOTE
set -euo pipefail
chmod 755 /usr/local/bin/slamface-deploy
if [[ ! -d $BASE/repo/.git ]]; then
  sudo -u deploy GIT_SSH_COMMAND="ssh -i /home/deploy/.ssh/spindlebox_repo_ed25519 -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new" \
    git clone git@github.com:moonsoup/spindlebox.git "$BASE/repo"
fi
cp "$BASE/repo/slamface/.env.example" "$BASE/repo/slamface/.env"
chown deploy:deploy "$BASE/repo/slamface/.env" && chmod 600 "$BASE/repo/slamface/.env"
sudo -u deploy /usr/local/bin/slamface-deploy
REMOTE

echo "provisioned. Next: bash $(dirname "$0")/provision.sh --audit"
