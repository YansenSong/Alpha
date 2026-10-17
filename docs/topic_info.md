# NeuPAN 导航栈话题信息

本项目使用 Smac Hybrid-A* 全局规划，以及 NeuPAN 局部规划与控制。

## 1. NeuPAN 导航栈

### 1.1 数据流

```text
/initialpose -> LIORF 定位

/goal_pose -> smac_neupan_bridge -> Smac planner
                                      ├── /plan -> NeuPAN
                                      └── /navigation/planner_state -> nav_status_node

/scan + /plan -> NeuPAN
NeuPAN -> /neupan_cmd_vel_raw -> neupan_ackermann_adapter
        -> /neupan_cmd_vel -> cmd_vel_mux
        -> /ackermann_steering_controller/reference
```

### 1.2 话题列表

| 话题 | 消息类型 | 方向 | 关键格式/作用 |
|---|---|---|---|
| `/initialpose` | `geometry_msgs/msg/PoseWithCovarianceStamped` | 输入 | `header.frame_id=map`；`pose.pose` 为初始位姿，`pose.covariance` 为协方差 |
| `/goal_pose` | `geometry_msgs/msg/PoseStamped` | 输入 | `header.frame_id=map`；`pose.position` 为目标位置，`pose.orientation` 为目标朝向 |
| `/map` | `nav_msgs/msg/OccupancyGrid` | 输出 | 2D 栅格地图；`info.resolution` 为分辨率，`data[]` 为栅格占用值 |
| `/plan` | `nav_msgs/msg/Path` | 输出/输入 | Smac 全局路径；`header.frame_id=map`，`poses[]` 为路径点序列 |
| `/plan_path` | `nav_msgs/msg/Path` | 输出 | `smac_neupan_bridge` 发布的兼容路径，供 RViz 使用 |
| `/global_path_remaining_distance` | `std_msgs/msg/Float64` | 输出 | `data` 为沿全局路径到目标点的剩余距离，单位为 m |
| `/scan` | `sensor_msgs/msg/LaserScan` | 输入 | `header.frame_id=laser_link`；`ranges[]` 为激光距离，单位为 m |
| `/neupan_plan` | `nav_msgs/msg/Path` | 输出 | NeuPAN 优化后的局部轨迹 |
| `/neupan_ref_state` | `nav_msgs/msg/Path` | 输出 | NeuPAN 参考状态 |
| `/neupan_initial_path` | `nav_msgs/msg/Path` | 输出 | NeuPAN 接收和处理的初始路径 |
| `/neupan_cmd_vel_raw` | `geometry_msgs/msg/Twist` | 输出 | `linear.x=v`；`angular.z` 表示 NeuPAN 输出的虚拟前轮转角 |
| `/neupan_cmd_vel` | `geometry_msgs/msg/Twist` | 输出 | `linear.x=v`；`angular.z=ω`，已由轴距和转角换算为车体偏航角速度 |
| `/stop` | `std_msgs/msg/Bool` | 输入 | `data=true` 覆盖速度命令并停车；`false` 解除覆盖 |
| `/navigation/state` | `nav_status/msg/NavigationStatus` | 输出 | `stamp`、`state`、`detail`；状态值见下表 |
| `/navigation/execution_state` | `nav_status/msg/NavigationExecution` | 输出 | nav_status 发布的权威导航结果，携带目标、路径标识和终态证据 |
| `/navigation/planner_state` | `nav_status/msg/NavigationExecution` | 内部 | 规划桥发布的带目标/路径标识的规划及安装状态 |
| `/neupan/controller_feedback` | `nav_status/msg/ControllerFeedback` | 内部 | NeuPAN 发布的带路径标识、定位观测时间和控制器到达标志的反馈 |
| `/global_plan/status` | `std_msgs/msg/String` | 内部 | Smac bridge 发布 `planning`、`succeeded` 或带原因的 `failed:` 状态 |
| `/neupan/arrived` | `std_msgs/msg/Bool` | 内部 | NeuPAN 的兼容到达信号，不参与权威结果判定 |
| `/ackermann_steering_controller/reference` | `geometry_msgs/msg/TwistStamped` | 输出 | `header.stamp`、`header.frame_id=base_link`；`twist.linear.x=v`，`twist.angular.z=ω` |

`NavigationStatus.msg` 格式：

```text
builtin_interfaces/Time stamp
uint8 state
string detail
```

状态值：

```text
WAITING_FOR_GOAL = 0
PLANNING         = 1
MOVING           = 2
ARRIVED          = 3
FAILED           = 4
```

## 2. 定位、传感器和底盘话题

| 话题 | 消息类型 | 关键格式/作用 |
|---|---|---|
| `/points_raw` | `sensor_msgs/msg/PointCloud2` | Gazebo 3D 激光雷达原始点云 |
| `/points_lio` | `sensor_msgs/msg/PointCloud2` | LIORF 使用的点云，包含 `ring/time` 等字段 |
| `/imu/data` | `sensor_msgs/msg/Imu` | IMU 线加速度和角速度 |
| `/odom` | `nav_msgs/msg/Odometry` | LIORF 输出的定位里程计 |
| `/odom_wheel` | `nav_msgs/msg/Odometry` | Ackermann 控制器输出的轮速里程计，NeuPAN 栈的 `nav_status_node` 使用 |
| `/joint_states` | `sensor_msgs/msg/JointState` | 关节位置、速度和力矩状态 |
| `/tf` | `tf2_msgs/msg/TFMessage` | 动态坐标变换，如 `map -> odom -> base_link` |
| `/tf_static` | `tf2_msgs/msg/TFMessage` | 静态坐标变换，如 `base_link -> laser_link` |
| `/clock` | `rosgraph_msgs/msg/Clock` | Gazebo 仿真时间 |

## 3. 控制命令格式

NeuPAN 控制链最终向 `/ackermann_steering_controller/reference` 发布
`TwistStamped`：

| 话题 | `linear.x` | `angular.z` |
|---|---|---|
| `/neupan_cmd_vel_raw` | 线速度 `v` | 虚拟前轮转角 `δ` |
| `/neupan_cmd_vel` | 线速度 `v` | 车体偏航角速度 `ω` |
| `/ackermann_steering_controller/reference` | 线速度 `v` | 偏航角速度 `ω` |

`/neupan_cmd_vel_raw.angular.z` 是虚拟前轮转角，不能直接作为底盘偏航角速度；
`neupan_ackermann_adapter` 负责将其转换为 `/neupan_cmd_vel.angular.z`。
