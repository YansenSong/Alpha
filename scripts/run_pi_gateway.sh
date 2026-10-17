#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATEWAY_DIR="${PROJECT_ROOT}/third_party/RobotPilot/agent-gateway"
if [[ ! -d "${GATEWAY_DIR}/node_modules" ]]; then
  echo "Run npm ci --prefix ${GATEWAY_DIR} first." >&2
  exit 1
fi
exec node "${GATEWAY_DIR}/src/index.mjs" "$@"
