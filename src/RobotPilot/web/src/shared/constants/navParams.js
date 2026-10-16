// Curated Nav2 parameter list and value decoding for read-only support-package
// snapshots.

export const PARAM_ROWS_STORAGE_KEY = "robotpilotParamRows";

// A starter set of commonly-tuned Nav2 parameters. Exact names depend on the
// robot's Nav2 config, so every field is editable and the list is persisted —
// operators curate their own working set. Node is the fully-qualified node
// name; the get/set services live at <node>/{get,set}_parameters.
export const DEFAULT_PARAM_ROWS = [
  { node: "/controller_server", param: "FollowPath.max_vel_x", type: "double" },
  { node: "/controller_server", param: "FollowPath.max_vel_theta", type: "double" },
  { node: "/controller_server", param: "general_goal_checker.xy_goal_tolerance", type: "double" },
  { node: "/planner_server", param: "GridBased.tolerance", type: "double" },
  { node: "/global_costmap/global_costmap", param: "inflation_layer.inflation_radius", type: "double" },
  { node: "/local_costmap/local_costmap", param: "inflation_layer.inflation_radius", type: "double" },
];

// rcl_interfaces/msg/ParameterType values.
export const PARAM_TYPES = { bool: 1, int: 2, double: 3, string: 4 };

export const readParamValue = (pv) => {
  if (!pv) return "";
  switch (pv.type) {
    case PARAM_TYPES.bool:
      return String(pv.bool_value);
    case PARAM_TYPES.int:
      return String(pv.integer_value);
    case PARAM_TYPES.double:
      return String(pv.double_value);
    case PARAM_TYPES.string:
      return pv.string_value;
    default:
      return "";
  }
};

export const loadParamRows = () => {
  try {
    const stored = JSON.parse(localStorage.getItem(PARAM_ROWS_STORAGE_KEY) || "null");
    return Array.isArray(stored) && stored.length ? stored : DEFAULT_PARAM_ROWS;
  } catch {
    return DEFAULT_PARAM_ROWS;
  }
};
