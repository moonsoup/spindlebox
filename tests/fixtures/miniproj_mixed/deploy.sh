#!/bin/bash
set -euo pipefail

# Deploy the thing to the target environment.
deploy() {
  local target="$1"
  echo "deploying ${target} to ${DEPLOY_ENV}"
  build
}

# Build everything.
build() {
  make all
}

deploy "$@"
