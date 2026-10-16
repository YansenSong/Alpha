# AckermannRobot-3D-ROS2 — Real Vehicle Integration

本分支只保留实车部署链路，不包含 Gazebo、ros2_control 仿真控制器或仿真地图/启动脚本。

## 1. 主要组件

- `config/vehicle.yaml`：项目级车辆几何、硬限制、规划限制、LiDAR/IMU 外参的唯一配置源（不是 ROS package）
- `src/mapping/lio-sam`：建图
- `src/localization/liorf_localization`：先验地图定位
- `src/planning/nav2_smac_planner`、`src/planning/smac_neupan_bridge`：Smac 全局规划及目标/路径桥接
- `src/control/neupan_ros2`、`src/control/motion_interface`：局部规划、命令安全门及 STM32 UDP 实车接口
- `src/bringup/nav_neupan_bringup`：Smac + NeuPAN 导航栈启动包
- `src/bringup/vehicle_bringup`：共用实车传感器、运动接口和定位启动
- `src/extension/nav_status`：导航状态监控
- `src/sensors/lidar`、`src/sensors/imu`：LiDAR 与 IMU 传感器驱动
- `src/extension/nav_pointcloud_filter`：导航点云车体过滤

上述分类目录不是 ROS 功能包；各包名称以其 `package.xml` 为准。

## 2. 编译

```bash
source /opt/ros/humble/setup.bash
git submodule sync --recursive
git submodule update --init --recursive
colcon build --base-paths src --symlink-install --allow-overriding nav2_smac_planner
source install/setup.bash
```

## 3. 项目级车辆参数

车辆物理、运动和传感器安装参数统一放在仓库根目录：

```text
config/vehicle.yaml
```

它不是 ROS package。实车启动链路把它的绝对路径传给各模块，再分别映射到 `motion_interface`、Smac + NeuPAN 导航栈、LIORF 和 LIO-SAM。

主要职责：

- `geometry`：车长、车宽、轴距、轮距、轮胎尺寸、前后悬
- `control_limits`：STM32 执行侧硬限制
- `planning`：Smac、NeuPAN 共用的规划/运动约束和 footprint
- `sensor_extrinsics.lidar_to_imu`：LIORF 与 LIO-SAM 共用的 LiDAR/IMU 外参

当前车辆几何和 footprint 已标记为 `VERIFIED`；底盘速度/转角硬限制和 LiDAR/IMU 外参仍需要实车确认。设备 IP、端口、串口等部署参数继续留在各自驱动/接口配置中。

LiDAR/IMU 外参直接对应 LIO-SAM/LIORF：

```yaml
vehicle:
  sensor_extrinsics:
    lidar_to_imu:
      status: "VERIFIED"
      translation_xyz: [x, y, z]
      rotation_matrix: [r00, r01, r02, r10, r11, r12, r20, r21, r22]
      orientation_matrix: [r00, r01, r02, r10, r11, r12, r20, r21, r22]
```

外参未标记为 `VERIFIED` 时，LIORF 和 LIO-SAM 都会拒绝启动。

## 4. 实车启动入口

```bash
./scripts/start_vehicle.sh lidar
./scripts/start_vehicle.sh imu
./scripts/start_vehicle.sh bridge
./scripts/start_vehicle.sh all
```

启动 Smac Hybrid-A* + NeuPAN 导航：

```bash
./scripts/start_vehicle.sh nav maps/<map_name>
```

## 5. 统一实车控制接口

最终 STM32 接口始终使用：

```text
/ackermann_cmd
  linear.x  = longitudinal speed [m/s]
  angular.z = front-wheel steering angle [rad]
```

### Smac + NeuPAN

```text
Smac Hybrid-A*
  -> /plan
  -> NeuPAN
  -> /neupan_cmd_vel_raw        (speed + steering angle)
  -> motion_interface/command_gate
  -> /ackermann_cmd
  -> motion_interface/stm32_bridge
  -> STM32
```

## 6. 导航车辆参数

Smac + NeuPAN 从根目录 `config/vehicle.yaml` 获取最小转弯半径、车体几何、footprint 和规划速度。

## 7. 定位与建图

导航栈使用 LIORF 先验地图定位，并要求根配置中的 LiDAR/IMU 外参为 `VERIFIED`。

LIO-SAM 建图（LiDAR + IMU + LIO-SAM 一次拉起，不启动运动接口，推车走一圈即可）：

```bash
bash scripts/start_vehicle.sh mapping
```

坐标系、LiDAR/IMU 外参和雷达安装位姿都由启动文件从 `config/vehicle.yaml` 注入，不写在各包的参数文件里。

存图与转图：

```bash
ros2 service call /lio_sam/save_map lio_sam/srv/SaveMap \
  "{resolution: 0.2, destination: $(pwd)/maps}"
# 产出 maps/<时间戳>/GlobalMap.pcd，再用该时间戳目录转 2D 图
bash scripts/pcd_to_map.sh maps/<时间戳>
```

`pcd2gridmap` 是普通 CMake 工程，首次使用前需要编译：

```bash
cmake -S third_party/pcd2pgm -B third_party/pcd2pgm/build
cmake --build third_party/pcd2pgm/build
```

## 8. 地图

`maps/` 只用于存放实车地图。导航目录应包含：

```text
map.yaml
map.pgm
GlobalMap.pcd
```
