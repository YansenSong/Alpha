#!/usr/bin/env bash
#==========================================
# 实车启动脚本 (ROS 2 Humble)
#
#   lidar   启动 Hesai LiDAR + RViz2
#   imu     仅启动 LPMS-IG1 IMU
#   bridge  仅启动 STM32 运动接口后端 (motion_interface)
#   status  仅启动 sta__ 状态接收（不发任何控制帧，用于台架联调）
#   all     启动 LiDAR + RViz2 + STM32 运动接口（不自动启动 IMU）
#   nav     启动 Smac Hybrid-A* + NeuPAN 完整导航栈
#   mapping 启动 LIO-SAM 建图（LiDAR + IMU + LIO-SAM），不下发任何控制
#==========================================

set -eo pipefail

ROS2_DISTRO="${ROS2_DISTRO:-humble}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VEHICLE_CONFIG="${VEHICLE_CONFIG:-${PROJECT_DIR}/config/vehicle.yaml}"
LIDAR_CONFIG="${LIDAR_CONFIG:-${PROJECT_DIR}/src/sensors/lidar/config/config.yaml}"
IMU_PORT="${IMU_PORT:-/dev/ttyUSB0}"
IMU_SENSOR_ID="${IMU_SENSOR_ID:-1}"
IMU_PARAMS_FILE="${IMU_PARAMS_FILE:-${PROJECT_DIR}/src/sensors/imu/config/lpms_ig1_rs232_calibration.yaml}"
INTERFACE_CONFIG="${PROJECT_DIR}/src/control/motion_interface/config/bridge_params.yaml"
STATUS_CONFIG="${PROJECT_DIR}/src/control/motion_interface/config/status_params.yaml"
MAPPING_RVIZ="${MAPPING_RVIZ:-true}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

usage() {
    cat <<EOF
用法: $0 <lidar|imu|bridge|status|all|nav|mapping> [map]

  lidar   启动 Hesai LiDAR + RViz2
  imu     仅启动 LPMS-IG1 IMU
  bridge  仅启动 motion_interface 的 STM32 后端
  status  仅启动 sta__ 状态接收，不下发任何控制帧（台架联调用）
  all     启动 LiDAR + RViz2 + STM32 运动接口（不自动启动 IMU）
  nav     启动 Smac Hybrid-A* + NeuPAN 完整导航栈
          map 可传地图目录、map.yaml 或 map.pgm
  nav 地图目录需包含 map.yaml、map.pgm、GlobalMap.pcd
  mapping 启动 LIO-SAM 建图：LiDAR + IMU + LIO-SAM + LIO-SAM RViz
          不启动运动接口，建图时推车/遥控移动即可

环境变量:
  VEHICLE_CONFIG 项目级车辆参数，默认: config/vehicle.yaml
  LIDAR_CONFIG   Hesai 配置文件，默认: src/sensors/lidar/config/config.yaml
  IMU_PORT       LPMS RS232 串口，默认: /dev/ttyUSB0
  IMU_SENSOR_ID  LPMS 传感器 ID，默认: 1
  IMU_PARAMS_FILE LPMS 软件标定文件，默认使用项目内标定结果
  ROS2_DISTRO    ROS 发行版，默认: humble
  MAPPING_RVIZ   mapping 模式是否开 RViz，默认: true（置 false 可无头建图）

示例:
  $0 lidar
  $0 imu
  $0 bridge
  $0 status
  $0 all
  $0 nav maps/my_map
  $0 mapping
  VEHICLE_CONFIG=/path/to/vehicle.yaml $0 bridge
  LIDAR_CONFIG=/path/to/hesai.yaml $0 lidar
  IMU_PORT=/dev/ttyUSB0 IMU_SENSOR_ID=1 $0 imu
  MAPPING_RVIZ=false $0 mapping
EOF
}

MODE="${1:-help}"
ENABLE_LIDAR=false
LIDAR_RVIZ=false
ENABLE_IMU=false
ENABLE_CONTROL=false
ENABLE_STATUS=false
ENABLE_NAVIGATION=false
NAVIGATION_RVIZ=false
ENABLE_MAPPING=false

case "$MODE" in
    lidar)
        ENABLE_LIDAR=true
        LIDAR_RVIZ=true
        ;;
    imu)
        ENABLE_IMU=true
        ;;
    bridge)
        ENABLE_CONTROL=true
        ;;
    status)
        ENABLE_STATUS=true
        ;;
    all)
        ENABLE_LIDAR=true
        LIDAR_RVIZ=true
        ENABLE_CONTROL=true
        ;;
    nav)
        ENABLE_LIDAR=true
        ENABLE_CONTROL=true
        ENABLE_NAVIGATION=true
        NAVIGATION_RVIZ=true
        # LIORF cannot localize without the IMU (it deskews the cloud with it and
        # fuses it in the factor graph), so nav has to bring the IMU up too.
        ENABLE_IMU=true
        ;;
    mapping)
        # mapping.launch.py starts the LiDAR and the IMU itself; these two flags
        # are only turned on so this script's config validation and logging
        # apply to them the same way as in the other modes.
        ENABLE_LIDAR=true
        ENABLE_IMU=true
        ENABLE_MAPPING=true
        ;;
    help|-h|--help)
        usage
        exit 0
        ;;
    *)
        log_error "未知参数: $MODE"
        usage
        exit 1
        ;;
esac

ROS_SETUP="/opt/ros/${ROS2_DISTRO}/setup.bash"
if [[ ! -f "$ROS_SETUP" ]]; then
    log_error "未找到 ROS 2 ${ROS2_DISTRO}: ${ROS_SETUP}"
    exit 1
fi

WORKSPACE_SETUP="${PROJECT_DIR}/install/setup.bash"
if [[ ! -f "$WORKSPACE_SETUP" ]]; then
    log_error "未找到工作空间环境: ${WORKSPACE_SETUP}"
    log_error "请先在仓库根目录执行 colcon build --symlink-install"
    exit 1
fi

source "$ROS_SETUP"
source "$WORKSPACE_SETUP"

if $ENABLE_CONTROL || $ENABLE_NAVIGATION || $ENABLE_MAPPING; then
    if [[ ! -f "$VEHICLE_CONFIG" ]]; then
        log_error "车辆参数文件不存在: ${VEHICLE_CONFIG}"
        exit 1
    fi
    log_info "车辆参数: ${VEHICLE_CONFIG}"
fi

if $ENABLE_LIDAR; then
    if [[ ! -f "$LIDAR_CONFIG" ]]; then
        log_error "LiDAR 配置文件不存在: ${LIDAR_CONFIG}"
        exit 1
    fi
    log_info "LiDAR 配置: ${LIDAR_CONFIG}"
    if grep -Eq 'device_ip_address:[[:space:]]*""|udp_port:[[:space:]]*0([[:space:]]|$)' "$LIDAR_CONFIG"; then
        log_warn "LiDAR 配置仍包含空 IP 或 udp_port=0；请确认已填写实车参数。"
    fi
fi

if $ENABLE_IMU; then
    if [[ ! -f "$IMU_PARAMS_FILE" ]]; then
        log_error "IMU 标定文件不存在: ${IMU_PARAMS_FILE}"
        exit 1
    fi
    log_info "IMU RS232: ${IMU_PORT}, sensor ID: ${IMU_SENSOR_ID}"
    log_info "IMU 标定文件: ${IMU_PARAMS_FILE}"
fi

if $ENABLE_CONTROL; then
    if [[ ! -f "$INTERFACE_CONFIG" ]]; then
        log_error "motion_interface 配置不存在: ${INTERFACE_CONFIG}"
        exit 1
    fi
    log_info "motion_interface 配置: ${INTERFACE_CONFIG}"
fi

# The bridge also starts the sta__ receiver (real_vehicle.launch.py leaves
# enable_status_receiver at its default), so this file is needed whenever
# either the bridge or the receiver is launched.
if $ENABLE_CONTROL || $ENABLE_STATUS; then
    if [[ ! -f "$STATUS_CONFIG" ]]; then
        log_error "sta__ 接收配置不存在: ${STATUS_CONFIG}"
        exit 1
    fi
    log_info "sta__ 接收配置: ${STATUS_CONFIG}"
fi

MAP_YAML=""
MAP_PGM=""
GLOBALMAP_PCD=""

if $ENABLE_NAVIGATION; then
    MAP_ARG="${2:-}"
    if [[ -z "$MAP_ARG" ]]; then
        log_error "${MODE} 模式需要地图目录、map.yaml 或 map.pgm"
        usage
        exit 1
    fi

    if [[ "$MAP_ARG" != /* ]]; then
        MAP_ARG="${PROJECT_DIR}/${MAP_ARG}"
    fi

    if [[ -d "$MAP_ARG" ]]; then
        MAP_DIR="$(realpath -m "$MAP_ARG")"
    elif [[ -f "$MAP_ARG" ]]; then
        MAP_DIR="$(dirname "$(realpath -m "$MAP_ARG")")"
    else
        log_error "地图路径不存在: ${MAP_ARG}"
        exit 1
    fi

    MAP_YAML="${MAP_DIR}/map.yaml"
    MAP_PGM="${MAP_DIR}/map.pgm"
    GLOBALMAP_PCD="${MAP_DIR}/GlobalMap.pcd"

    for required in "$MAP_YAML" "$MAP_PGM" "$GLOBALMAP_PCD"; do
        if [[ ! -f "$required" ]]; then
            log_error "缺少导航地图文件: ${required}"
            exit 1
        fi
    done

    log_info "导航地图目录: ${MAP_DIR}"
    log_info "导航栈: Smac + NeuPAN"
fi

echo ""
log_info "=============================="
log_info "  实车启动模式: ${MODE}"
log_info "=============================="

if [[ "$MODE" == "mapping" ]]; then
    LAUNCH_CMD=(
        ros2 launch vehicle_bringup mapping.launch.py
        "vehicle_config:=${VEHICLE_CONFIG}"
        "lidar_config:=${LIDAR_CONFIG}"
        "enable_imu:=${ENABLE_IMU}"
        "imu_port:=${IMU_PORT}"
        "imu_sensor_id:=${IMU_SENSOR_ID}"
        "imu_params_file:=${IMU_PARAMS_FILE}"
        "points_topic:=/lidar_points"
        "use_sim_time:=false"
        "use_rviz:=${MAPPING_RVIZ}"
    )
elif [[ "$MODE" == "nav" ]]; then
    LAUNCH_CMD=(
        ros2 launch nav_neupan_bringup navigation.launch.py
        "project_dir:=${PROJECT_DIR}"
        "vehicle_config:=${VEHICLE_CONFIG}"
        "map:=${MAP_YAML}"
        "map_pgm:=${MAP_PGM}"
        "globalmap_pcd:=${GLOBALMAP_PCD}"
        "points_topic:=/lidar_points"
        "start_hardware:=true"
        "lidar_config:=${LIDAR_CONFIG}"
        "enable_imu:=${ENABLE_IMU}"
        "imu_port:=${IMU_PORT}"
        "imu_sensor_id:=${IMU_SENSOR_ID}"
        "imu_params_file:=${IMU_PARAMS_FILE}"
        "bridge_params_file:=${INTERFACE_CONFIG}"
        "status_params_file:=${STATUS_CONFIG}"
        "use_sim_time:=false"
        "use_rviz:=${NAVIGATION_RVIZ}"
    )
elif [[ "$MODE" == "status" ]]; then
    # Bench bring-up only: receive and validate sta__ while commanding
    # nothing. Goes straight to motion_interface rather than real_vehicle so
    # that gate and bridge are unambiguously off.
    LAUNCH_CMD=(
        ros2 launch motion_interface motion_interface.launch.py
        "enable_command_gate:=false"
        "enable_stm32_bridge:=false"
        "enable_status_receiver:=true"
        "status_params_file:=${STATUS_CONFIG}"
    )
else
    LAUNCH_CMD=(
        ros2 launch vehicle_bringup real_vehicle.launch.py
        "vehicle_config:=${VEHICLE_CONFIG}"
        "enable_lidar:=${ENABLE_LIDAR}"
        "lidar_config:=${LIDAR_CONFIG}"
        "lidar_rviz:=${LIDAR_RVIZ}"
        "enable_imu:=${ENABLE_IMU}"
        "imu_port:=${IMU_PORT}"
        "imu_sensor_id:=${IMU_SENSOR_ID}"
        "imu_params_file:=${IMU_PARAMS_FILE}"
        "enable_control:=${ENABLE_CONTROL}"
        "bridge_params_file:=${INTERFACE_CONFIG}"
        "status_params_file:=${STATUS_CONFIG}"
    )
fi

echo ""
log_info "启动 ROS 2 实车栈；按 Ctrl+C 停止。"
exec "${LAUNCH_CMD[@]}"
