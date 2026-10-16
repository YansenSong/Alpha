export const AppConfig = {
  ROSBRIDGE_SERVER_IP: "127.0.0.1",
  ROSBRIDGE_SERVER_PORT: "9090",
  RECONNECTION_TIME: 1000,
  MAX_RECONNECTION_TIME: 30000,

  CMD_VEL_TOPIC: "/cmd_vel",
  STOP_TOPIC: "/stop",
  SOFTWARE_STOP_REQUEST_TOPIC: "/safety/software_stop/request",
  SOFTWARE_STOP_STATE_TOPIC: "/safety/software_stop/state",
  ROBOT_POSE_TOPIC: "/odometry/filtered",
  ROBOT_VELOCITY_TOPIC: "/odometry/filtered",
  MAP_TOPIC: "/ui/map",
  GLOBAL_COSTMAP_TOPIC: "/global_costmap/costmap",
  LOCAL_COSTMAP_TOPIC: "/local_costmap/costmap",
  SCAN_TOPIC: "/scan",
  PLAN_TOPIC: "/plan",
  TF_TOPIC: "/tf",
  TF_STATIC_TOPIC: "/tf_static",
  UI_TF_STATIC_TOPIC: "/ui/tf_static",
  LOCALIZATION_POSE_TOPIC: "/liorf_localization/mapping/odometry",
  LOCALIZATION_POSE_TYPE: "nav_msgs/Odometry",
  NAVIGATION_STATE_TOPIC: "/navigation/state",
  NAVIGATION_STATE_TYPE: "nav_status/NavigationStatus",
  NAV_STATUS_TOPIC: "/ui/navigate_to_pose/status",
  NAV_FEEDBACK_TOPIC: "/navigate_to_pose/_action/feedback",
  NAV_CANCEL_GOAL_SERVICE: "/navigate_to_pose/_action/cancel_goal",
  DOCK_STATUS_TOPIC: "/ui/dock_robot/status",
  DOCK_TRIGGER_STATUS_TOPIC: "/dock_trigger_status",
  DOCK_TRIGGER_TOPIC: "/dock_trigger",
  UNDOCK_STATUS_TOPIC: "/ui/undock_robot/status",
  UNDOCK_TRIGGER_TOPIC: "/undock_robot",
  GOAL_POSE_TOPIC: "/goal_pose",
  MISSION_COMMAND_TOPIC: "/mission/command",
  MISSION_STATE_TOPIC: "/mission/state",
  MISSION_ACK_TOPIC: "/mission/ack",
  INITIAL_POSE_TOPIC: "/initialpose",
  UI_OPERATION_TOPIC: "/ui_operation",
  UI_MESSAGE_TOPIC: "/ui_message",
  UI_OPERATION: "/ui_operation",
  SET_POINT: "/may_set_point",
  WP_REQ: "/WP_req",
  SENSORS_TOPIC: "/sensors",
  BATTERY_TOPIC: "/battery_status",
  BATTERY_STATE_TOPIC: "/battery/state",
  CHARGE_STATION_CONNECTED: "/charge_station_connected",

  // 关节状态遥测（sensor_msgs/JointState），可供其他状态视图使用。
  JOINT_STATES_TOPIC: "/joint_states",

  // Route editor: file/waypoint exchange with robotpilot_ui_package's folders_handler node
  NAV_DATA_REQ_TOPIC: "/nav_data_req",
  NAV_DATA_RESP_TOPIC: "/nav_data_resp",
  ROUTE_DATA_REQ_TOPIC: "/ackermann/routes/request",
  ROUTE_DATA_RESP_TOPIC: "/ackermann/routes/catalog",
  NEW_WAYPOINT_TOPIC: "/new_way_point",
  ROUTE_PLAN_REQUEST_TOPIC: "/ackermann/routes/plan_request",
  ROUTE_PLAN_RESPONSE_TOPIC: "/ackermann/routes/plan_response",

  MAX_LINEAR_SPEED: 0.2,
  MAX_ANGULAR_SPEED: 2,
};

// Camera image topics selectable on the Camera panel; value must match a
// topic actually published by the robot/simulation stack or web_video_server
// will just show nothing for that selection.
export const CAMERA_TOPIC_OPTIONS = [
  { value: "/depth_camera/image_raw", label: "/depth_camera/image_raw" },
  {
    value: "/depth_camera/depth/image_raw",
    label: "/depth_camera/depth/image_raw",
  },
];
export const DEFAULT_CAMERA_TOPIC = "/depth_camera/image_raw";

// Lifecycle-managed Nav2 nodes launched by the current planning stack.
// `base` is the ROS node namespace exposing get_state/change_state services.
export const LIFECYCLE_NODES = [
  { name: "map_server", base: "/map_server" },
  { name: "planner", base: "/planner_server" },
];
