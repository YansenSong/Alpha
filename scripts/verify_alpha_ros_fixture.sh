#!/usr/bin/env bash
set -eo pipefail
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source /opt/ros/humble/setup.bash
source "${PROJECT_ROOT}/install/setup.bash"
export ROS_DOMAIN_ID=186
export PYTHONPATH="${PROJECT_ROOT}/src/extension/mission_manager:${PROJECT_ROOT}/third_party/RobotPilot/ros2/src/robotpilot_ui_package:${PROJECT_ROOT}/third_party/RobotPilot/ros2/src/robotpilot_ui_package/test:${PYTHONPATH:-}"
exec /usr/bin/python3 "${PROJECT_ROOT}/third_party/RobotPilot/alpha-mcp/tests/ros_platform_fixture.py"
