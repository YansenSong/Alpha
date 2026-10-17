#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MCP_ROOT="${PROJECT_ROOT}/third_party/RobotPilot/alpha-mcp"
if [[ ! -x "${MCP_ROOT}/.venv/bin/python" ]]; then
  echo "Run: uv sync --project ${MCP_ROOT} --locked" >&2
  exit 1
fi
case "${1:-alpha}" in
  alpha) exec "${MCP_ROOT}/.venv/bin/python" -m alpha_mcp.server ;;
  ros_inspect) exec "${MCP_ROOT}/.venv/bin/python" -m alpha_mcp.ros_inspect ;;
  *) echo "Unknown MCP server" >&2; exit 1 ;;
esac
