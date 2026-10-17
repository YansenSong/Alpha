// Copyright (c) 2026 AckermannRobot contributors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include "smac_neupan_bridge/smac_neupan_bridge.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <functional>
#include <limits>
#include <stdexcept>
#include <utility>
#include <nlohmann/json.hpp>

#include "tf2/exceptions.h"
#include "tf2_geometry_msgs/tf2_geometry_msgs.hpp"
#include "tf2/time.h"

namespace smac_neupan_bridge
{

AckermannSmacBridge::AckermannSmacBridge(const rclcpp::NodeOptions & options)
: Node("smac_neupan_bridge", options)
{
  global_frame_ = declare_parameter<std::string>("global_frame", "map");
  robot_frame_ = declare_parameter<std::string>("robot_frame", "rear_axle_link");
  action_name_ = declare_parameter<std::string>(
    "planner_action", "/compute_path_to_pose");
  planner_id_ = declare_parameter<std::string>("planner_id", "GridBased");
  goal_topic_ = declare_parameter<std::string>("goal_topic", "/goal_pose");
  plan_path_topic_ = declare_parameter<std::string>("plan_path_topic", "/plan_path");
  execution_path_topic_ = declare_parameter<std::string>("execution_path_topic", "/plan");
  remaining_distance_topic_ = declare_parameter<std::string>(
    "remaining_distance_topic", "/global_path_remaining_distance");
  planning_status_topic_ = declare_parameter<std::string>(
    "planning_status_topic", "/global_plan/status");
  tf_timeout_ = declare_parameter<double>("tf_timeout", 0.2);
  publish_rate_ = declare_parameter<double>("publish_rate", 10.0);
  action_server_wait_timeout_ = declare_parameter<double>(
    "action_server_wait_timeout", 2.0);

  if (global_frame_.empty() || robot_frame_.empty() || action_name_.empty()) {
    throw std::invalid_argument("global_frame, robot_frame and planner_action must not be empty");
  }
  if (tf_timeout_ <= 0.0) {
    RCLCPP_WARN(get_logger(), "tf_timeout must be positive; using 0.2 seconds");
    tf_timeout_ = 0.2;
  }
  if (publish_rate_ <= 0.0) {
    RCLCPP_WARN(get_logger(), "publish_rate must be positive; using 10 Hz");
    publish_rate_ = 10.0;
  }
  if (action_server_wait_timeout_ < 0.0) {
    RCLCPP_WARN(
      get_logger(), "action_server_wait_timeout must be non-negative; using 2 seconds");
    action_server_wait_timeout_ = 2.0;
  }

  const auto qos = rclcpp::QoS(rclcpp::KeepLast(10)).reliable();
  goal_sub_ = create_subscription<geometry_msgs::msg::PoseStamped>(
    goal_topic_, qos, std::bind(&AckermannSmacBridge::onGoal, this, std::placeholders::_1));
  plan_path_pub_ = create_publisher<nav_msgs::msg::Path>(plan_path_topic_, qos);
  execution_path_pub_ = create_publisher<nav_msgs::msg::Path>(execution_path_topic_, qos);
  remaining_distance_pub_ = create_publisher<std_msgs::msg::Float64>(
    remaining_distance_topic_, qos);
  auto status_qos = rclcpp::QoS(rclcpp::KeepLast(1)).reliable().transient_local();
  planning_status_pub_ = create_publisher<std_msgs::msg::String>(
    planning_status_topic_, status_qos);
  execution_status_pub_ = create_publisher<nav_status::msg::NavigationExecution>(
    "/navigation/planner_state", status_qos);
  navigation_result_sub_ = create_subscription<nav_status::msg::NavigationExecution>(
    "/navigation/execution_state", status_qos,
    std::bind(&AckermannSmacBridge::onNavigationResult, this, std::placeholders::_1));
  rules_hold_pub_ = create_publisher<std_msgs::msg::Bool>("/navigation/rules_hold", qos);
  rules_status_pub_ = create_publisher<std_msgs::msg::String>("/navigation/rules_status", qos);
  rules_sub_ = create_subscription<std_msgs::msg::String>("/area_rules/state", status_qos,
    std::bind(&AckermannSmacBridge::onRules, this, std::placeholders::_1));
  path_installed_sub_ = create_subscription<std_msgs::msg::String>("/neupan/path_install_status", qos,
    std::bind(&AckermannSmacBridge::onPathInstalled, this, std::placeholders::_1));
  mask_sub_ = create_subscription<nav_msgs::msg::OccupancyGrid>("/area_rules/keepout_mask", status_qos,
    std::bind(&AckermannSmacBridge::onMask, this, std::placeholders::_1));
  costmap_sub_ = create_subscription<nav_msgs::msg::OccupancyGrid>("/global_costmap/costmap", qos,
    std::bind(&AckermannSmacBridge::onCostmap, this, std::placeholders::_1));

  tf_buffer_ = std::make_shared<tf2_ros::Buffer>(get_clock());
  tf_listener_ = std::make_shared<tf2_ros::TransformListener>(*tf_buffer_);
  action_client_ = rclcpp_action::create_client<ComputePathToPose>(this, action_name_);

  const auto period = std::chrono::duration_cast<std::chrono::milliseconds>(
    std::chrono::duration<double>(1.0 / publish_rate_));
  remaining_distance_timer_ = create_wall_timer(
    std::max(std::chrono::milliseconds(1), period),
    std::bind(&AckermannSmacBridge::publishRemainingDistance, this));
  rules_timer_ = create_wall_timer(std::chrono::milliseconds(100),
    std::bind(&AckermannSmacBridge::checkRules, this));

  active_path_.header.frame_id = global_frame_;

  RCLCPP_INFO(
    get_logger(),
    "Bridging %s goals to %s using planner '%s'; planning frame=%s, robot frame=%s",
    goal_topic_.c_str(), action_name_.c_str(), planner_id_.c_str(),
    global_frame_.c_str(), robot_frame_.c_str());
}

void AckermannSmacBridge::onGoal(
  const geometry_msgs::msg::PoseStamped::SharedPtr msg)
{
  if (!msg) {
    return;
  }

  requested_goal_ = *msg;
  try {
    saved_goal_ = transformGoal(*msg);
    have_goal_ = true;
    map_requires_new_goal_ = false;
    navigation_failed_ = false;
    active_path_.poses.clear();
    path_installed_ = false;
    rules_hold_ = true;
  } catch (const tf2::TransformException & ex) {
    publishPlanningStatus(std::string("failed: cannot transform goal: ") + ex.what());
    return;
  }
  planToSavedGoal();
}

void AckermannSmacBridge::planToSavedGoal()
{
  if (!have_goal_ || !have_rules_ || !rules_ready_ || !costmapApplied()) {
    rules_hold_ = true;
    publishPlanningStatus("rule_replan_pending");
    return;
  }

  publishPlanningStatus("planning");

  GoalHandle::SharedPtr previous_goal;
  std::uint64_t generation;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    generation = ++goal_generation_;
    planning_ = true;
    planning_rules_version_ = rules_version_;
    planning_mask_generation_ = mask_generation_;
    waiting_install_ = false;
    path_installed_ = false;
    previous_goal = active_goal_handle_;
    active_goal_handle_.reset();
    active_path_ = nav_msgs::msg::Path();
    active_path_.header.frame_id = global_frame_;

    // Clear the compatibility path atomically with the generation change so a
    // late result from the previous goal cannot repopulate it after this call.
    nav_msgs::msg::Path empty_path = active_path_;
    empty_path.header.stamp = now();
    plan_path_pub_->publish(empty_path);
  }

  if (previous_goal) {
    (void)action_client_->async_cancel_goal(previous_goal);
  }

  geometry_msgs::msg::PoseStamped goal;
  geometry_msgs::msg::PoseStamped start;
  try {
    goal = saved_goal_;
    start = currentRobotPose();
  } catch (const tf2::TransformException & ex) {
    planning_ = false;
    RCLCPP_ERROR(get_logger(), "Cannot prepare Smac goal: %s", ex.what());
    publishPlanningStatus(std::string("failed: cannot prepare goal: ") + ex.what());
    return;
  }

  if (!action_client_->wait_for_action_server(
      std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::duration<double>(action_server_wait_timeout_))))
  {
    planning_ = false;
    RCLCPP_ERROR(
      get_logger(), "Planner action '%s' is not available", action_name_.c_str());
    publishPlanningStatus("failed: planner action server unavailable");
    return;
  }

  ComputePathToPose::Goal action_goal;
  action_goal.start = std::move(start);
  action_goal.goal = std::move(goal);
  action_goal.planner_id = planner_id_;
  action_goal.use_start = true;

  ActionClient::SendGoalOptions options;
  options.goal_response_callback =
    [this, generation](GoalHandle::SharedPtr goal_handle) {
      onGoalResponse(generation, std::move(goal_handle));
    };
  options.result_callback =
    [this, generation](const GoalHandle::WrappedResult & wrapped_result) {
      onResult(generation, wrapped_result);
    };

  (void)action_client_->async_send_goal(action_goal, options);
}

void AckermannSmacBridge::onGoalResponse(
  const std::uint64_t generation, GoalHandle::SharedPtr goal_handle)
{
  if (!goal_handle) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (generation == goal_generation_) {
      RCLCPP_ERROR(get_logger(), "PlannerServer rejected the Smac planning goal");
      publishPlanningStatus("failed: planner rejected goal");
    }
    return;
  }

  bool stale = false;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    stale = generation != goal_generation_;
    if (!stale) {
      active_goal_handle_ = goal_handle;
    }
  }

  if (stale) {
    (void)action_client_->async_cancel_goal(goal_handle);
  }
}

void AckermannSmacBridge::onResult(
  const std::uint64_t generation,
  const GoalHandle::WrappedResult & wrapped_result)
{
  if (wrapped_result.code != rclcpp_action::ResultCode::SUCCEEDED ||
    !wrapped_result.result || wrapped_result.result->path.poses.empty())
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (generation != goal_generation_) {
      return;
    }

    active_goal_handle_.reset();
    planning_ = false;
    active_path_ = nav_msgs::msg::Path();
    active_path_.header.frame_id = global_frame_;
    active_path_.header.stamp = now();
    plan_path_pub_->publish(active_path_);
    RCLCPP_WARN(
      get_logger(), "Smac planning failed or returned an empty path (result code=%d)",
      static_cast<int>(wrapped_result.code));
    rules_hold_ = true;
    next_replan_at_ = now() + rclcpp::Duration::from_seconds(2.0);
    publishPlanningStatus("rule_replan_pending");
    return;
  }

  std::lock_guard<std::mutex> lock(mutex_);
  if (generation != goal_generation_) {
    return;
  }

  active_goal_handle_.reset();
  planning_ = false;
  if (!costmapApplied() || planning_rules_version_ != rules_version_ ||
    planning_mask_generation_ != mask_generation_ || pathBlocked(wrapped_result.result->path)) {
    rules_hold_ = true;
    next_replan_at_ = now() + rclcpp::Duration::from_seconds(1.0);
    publishPlanningStatus("rule_replan_pending");
    return;
  }
  // Preserve Smac's complete path, including orientation at Reeds-Shepp
  // reverse segments. The bridge deliberately does not recompute yaw.
  active_path_ = wrapped_result.result->path;
  // A unique installation identity, even if two paths finish on one clock tick.
  last_path_identity_ns_ = std::max(now().nanoseconds(), last_path_identity_ns_ + 1);
  active_path_.header.stamp = rclcpp::Time(last_path_identity_ns_, RCL_ROS_TIME);
  plan_path_pub_->publish(active_path_);
  // Only paths requested through /goal_pose are sent to the controller.
  // Preview requests use the same planner action but never enter this bridge.
  execution_path_pub_->publish(active_path_);
  waiting_install_ = true;
  path_installed_ = false;
  rules_hold_ = true;
  publishPlanningStatus("rule_replan_pending");

  RCLCPP_INFO(
    get_logger(), "Smac planning succeeded: %zu poses in %.3f seconds",
    active_path_.poses.size(),
    static_cast<double>(wrapped_result.result->planning_time.sec) +
    static_cast<double>(wrapped_result.result->planning_time.nanosec) * 1e-9);
}

void AckermannSmacBridge::onNavigationResult(
  const nav_status::msg::NavigationExecution::SharedPtr msg)
{
  // Consume the authority's terminal result. Do not replan an already finished
  // goal when a later area-rule update invalidates its old path.
  if (msg->state != msg->ARRIVED && msg->state != msg->FAILED) {return;}
  GoalHandle::SharedPtr pending;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!have_goal_ || msg->goal != requested_goal_ ||
      (msg->state == msg->ARRIVED && msg->path_stamp != active_path_.header.stamp)) {return;}
    ++goal_generation_;
    navigation_failed_ = msg->state == msg->FAILED;
    have_goal_ = false;
    planning_ = false;
    waiting_install_ = false;
    path_installed_ = false;
    pending = active_goal_handle_;
    active_goal_handle_.reset();
    active_path_.poses.clear();
  }
  if (pending) {(void)action_client_->async_cancel_goal(pending);}
}

void AckermannSmacBridge::publishPlanningStatus(const std::string & status)
{
  std_msgs::msg::String message;
  message.data = status;
  planning_status_pub_->publish(message);
  nav_status::msg::NavigationExecution execution;
  execution.stamp = now();
  execution.goal = requested_goal_;
  execution.path_stamp = active_path_.header.stamp;
  execution.execution_id = std::to_string(requested_goal_.header.stamp.sec) + ":" +
    std::to_string(requested_goal_.header.stamp.nanosec);
  execution.state = status == "succeeded" ? execution.MOVING :
    (status.rfind("failed:", 0) == 0 ? execution.FAILED : execution.PLANNING);
  execution.held = status == "rule_replan_pending";
  execution.detail = status;
  execution_status_pub_->publish(execution);
}

void AckermannSmacBridge::onRules(const std_msgs::msg::String::SharedPtr msg)
{
  try {
    const auto state = nlohmann::json::parse(msg->data);
    const auto key = state.value("map_key", std::string{});
    const auto id = state.value("map_id", std::string{});
    const auto version_id = state.value("map_version_id", std::string{});
    const auto version = state.value("version", std::uint64_t{0});
    const auto generation = state.value("mask_generation", std::uint64_t{0});
    const auto stamp = state.value("mask_stamp", nlohmann::json::object());
    const auto stamp_sec = stamp.value("sec", -1);
    const auto stamp_nanosec = stamp.value("nanosec", 0u);
    const bool map_changed = have_rules_ && (key != rules_map_key_ || id != rules_map_id_ ||
      version_id != rules_map_version_id_);
    const bool changed = !have_rules_ || key != rules_map_key_ || id != rules_map_id_ ||
      version_id != rules_map_version_id_ || version != rules_version_ ||
      generation != mask_generation_;
    rules_map_key_ = key;
    rules_map_id_ = id;
    rules_map_version_id_ = version_id;
    rules_version_ = version;
    mask_generation_ = generation;
    expected_mask_sec_ = stamp_sec;
    expected_mask_nanosec_ = stamp_nanosec;
    rules_ready_ = state.value("ready", false) && !key.empty() && !id.empty();
    have_rules_ = true;
    rules_received_at_ = now();
    if (changed || !rules_ready_) {
      rules_hold_ = true;
      costmap_verified_ = false;
      if (have_goal_) {
        publishPlanningStatus("rule_replan_pending");
      }
    }
    if (map_changed) {
      map_requires_new_goal_ = true;
      ++goal_generation_;
      if (active_goal_handle_) {(void)action_client_->async_cancel_goal(active_goal_handle_);}
      active_goal_handle_.reset();
      planning_ = false;
      have_goal_ = false;
      active_path_.poses.clear();
      path_installed_ = false;
      publishPlanningStatus("rule_replan_pending");
    }
  } catch (const std::exception & ex) {
    have_rules_ = false;
    rules_ready_ = false;
    rules_hold_ = true;
    RCLCPP_WARN(get_logger(), "Invalid area rules state: %s", ex.what());
  }
}

void AckermannSmacBridge::onMask(const nav_msgs::msg::OccupancyGrid::SharedPtr msg)
{
  mask_ = *msg;
  have_mask_ = true;
  mask_received_at_ = now();
  costmap_verified_ = false;
  rules_hold_ = true;
}

void AckermannSmacBridge::onCostmap(const nav_msgs::msg::OccupancyGrid::SharedPtr msg)
{
  costmap_ = *msg;
  have_costmap_ = true;
  costmap_received_at_ = now();
  costmap_verified_ = false;
  if (!have_mask_ || costmap_received_at_ < mask_received_at_ ||
    costmap_.header.frame_id != mask_.header.frame_id ||
    costmap_.info.resolution <= 0.0f || mask_.info.resolution <= 0.0f) {
    return;
  }
  const auto & info = mask_.info;
  if (std::abs(info.origin.orientation.z) > 1e-6 ||
    std::abs(costmap_.info.origin.orientation.z) > 1e-6) {
    return;
  }
  if (mask_.data.size() != static_cast<std::size_t>(info.width) * info.height) {
    return;
  }
  for (std::size_t i = 0; i < mask_.data.size(); ++i) {
    if (mask_.data[i] < 99) {
      continue;
    }
    const double x = info.origin.position.x + (static_cast<double>(i % info.width) + 0.5) * info.resolution;
    const double y = info.origin.position.y + (static_cast<double>(i / info.width) + 0.5) * info.resolution;
    const auto cx = static_cast<int>(std::floor((x - costmap_.info.origin.position.x) /
      costmap_.info.resolution));
    const auto cy = static_cast<int>(std::floor((y - costmap_.info.origin.position.y) /
      costmap_.info.resolution));
    if (cx < 0 || cy < 0 || cx >= static_cast<int>(costmap_.info.width) ||
      cy >= static_cast<int>(costmap_.info.height) ||
      costmap_.data[static_cast<std::size_t>(cy) * costmap_.info.width + cx] < 99) {
      return;
    }
  }
  costmap_verified_ = true;
}

bool AckermannSmacBridge::costmapApplied() const
{
  return have_rules_ && rules_ready_ && have_mask_ && have_costmap_ && costmap_verified_ &&
    mask_.header.stamp.sec == expected_mask_sec_ &&
    mask_.header.stamp.nanosec == expected_mask_nanosec_ &&
    (now() - rules_received_at_).seconds() <= 3.0 &&
    (now() - costmap_received_at_).seconds() <= 3.0;
}

bool AckermannSmacBridge::pathBlocked(const nav_msgs::msg::Path & path) const
{
  if (!have_mask_ || path.header.frame_id != mask_.header.frame_id ||
    mask_.info.resolution <= 0.0f || path.poses.empty() ||
    mask_.data.size() != static_cast<std::size_t>(mask_.info.width) * mask_.info.height) {
    return true;
  }
  const auto occupied = [this](double x, double y) {
      const auto & info = mask_.info;
      const int col = static_cast<int>(std::floor((x - info.origin.position.x) / info.resolution));
      const int row = static_cast<int>(std::floor((y - info.origin.position.y) / info.resolution));
      return col < 0 || row < 0 || col >= static_cast<int>(info.width) ||
             row >= static_cast<int>(info.height) ||
             mask_.data[static_cast<std::size_t>(row) * info.width + col] >= 99;
    };
  for (std::size_t i = 0; i < path.poses.size(); ++i) {
    const auto & p = path.poses[i].pose.position;
    if (occupied(p.x, p.y)) {return true;}
    if (i == 0) {continue;}
    const auto & a = path.poses[i - 1].pose.position;
    const auto steps = std::max(1, static_cast<int>(std::ceil(std::hypot(p.x - a.x, p.y - a.y) /
      (mask_.info.resolution * 0.5))));
    for (int step = 1; step < steps; ++step) {
      const double t = static_cast<double>(step) / steps;
      if (occupied(a.x + t * (p.x - a.x), a.y + t * (p.y - a.y))) {return true;}
    }
  }
  return false;
}

void AckermannSmacBridge::onPathInstalled(const std_msgs::msg::String::SharedPtr msg)
{
  try {
    const auto ack = nlohmann::json::parse(msg->data);
    if (waiting_install_ && ack.value("installed", false) &&
      ack.value("stamp_sec", -1) == active_path_.header.stamp.sec &&
      ack.value("stamp_nanosec", -1) == static_cast<int>(active_path_.header.stamp.nanosec) &&
      ack.value("pose_count", 0) == static_cast<int>(active_path_.poses.size())) {
      waiting_install_ = false;
      path_installed_ = true;
    }
  } catch (const std::exception &) {
    // Invalid controller acknowledgements never release the hold.
  }
}

void AckermannSmacBridge::checkRules()
{
  const bool applied = costmapApplied();
  const bool blocked = have_goal_ && !active_path_.poses.empty() && pathBlocked(active_path_);
  if (!applied || navigation_failed_ || map_requires_new_goal_ || blocked || planning_ || waiting_install_ ||
    (have_goal_ && !path_installed_)) {
    rules_hold_ = true;
  } else {
    if (rules_hold_ && have_goal_) {publishPlanningStatus("succeeded");}
    rules_hold_ = false;
  }
  if (have_goal_ && applied && (blocked || active_path_.poses.empty()) &&
    !planning_ && !waiting_install_ && now() >= next_replan_at_) {
    planToSavedGoal();
  }
  const std::string reason = navigation_failed_ ? "NAVIGATION_FAILED" : !have_rules_ || !rules_ready_ ? "WAITING_RULES" :
    !applied ? "WAITING_COSTMAP" : planning_ ? "REPLANNING" :
    waiting_install_ ? "PATH_INSTALL" : blocked ? "PATH_BLOCKED" :
    map_requires_new_goal_ ? "MAP_CHANGED" :
    have_goal_ && !path_installed_ ? "NO_VALID_PATH" : "READY";
  rules_hold_pub_->publish(std_msgs::msg::Bool().set__data(rules_hold_));
  nlohmann::json state = {{"applied", applied}, {"hold", rules_hold_},
    {"reason", reason},
    {"map_key", rules_map_key_}, {"map_id", rules_map_id_},
    {"map_version_id", rules_map_version_id_}, {"rules_version", rules_version_},
    {"mask_generation", mask_generation_}};
  rules_status_pub_->publish(std_msgs::msg::String().set__data(state.dump()));
}

geometry_msgs::msg::PoseStamped AckermannSmacBridge::transformGoal(
  const geometry_msgs::msg::PoseStamped & input) const
{
  auto goal = input;
  if (goal.header.frame_id.empty() || goal.header.frame_id == global_frame_) {
    goal.header.frame_id = global_frame_;
    return goal;
  }

  const auto transform = tf_buffer_->lookupTransform(
    global_frame_, goal.header.frame_id, tf2::TimePointZero,
    tf2::durationFromSec(tf_timeout_));
  geometry_msgs::msg::PoseStamped transformed;
  tf2::doTransform(goal, transformed, transform);
  transformed.header.frame_id = global_frame_;
  return transformed;
}

geometry_msgs::msg::PoseStamped AckermannSmacBridge::currentRobotPose() const
{
  const auto transform = tf_buffer_->lookupTransform(
    global_frame_, robot_frame_, tf2::TimePointZero,
    tf2::durationFromSec(tf_timeout_));

  geometry_msgs::msg::PoseStamped pose;
  pose.header = transform.header;
  pose.header.frame_id = global_frame_;
  pose.pose.position.x = transform.transform.translation.x;
  pose.pose.position.y = transform.transform.translation.y;
  pose.pose.position.z = transform.transform.translation.z;
  pose.pose.orientation = transform.transform.rotation;
  return pose;
}

double AckermannSmacBridge::remainingDistance(
  const nav_msgs::msg::Path & path, const double x, const double y)
{
  if (path.poses.empty()) {
    return 0.0;
  }
  if (path.poses.size() == 1) {
    return std::hypot(
      x - path.poses.front().pose.position.x,
      y - path.poses.front().pose.position.y);
  }

  std::vector<double> cumulative(path.poses.size(), 0.0);
  for (std::size_t i = 1; i < path.poses.size(); ++i) {
    const auto & a = path.poses[i - 1].pose.position;
    const auto & b = path.poses[i].pose.position;
    cumulative[i] = cumulative[i - 1] + std::hypot(b.x - a.x, b.y - a.y);
  }

  double best_distance_squared = std::numeric_limits<double>::max();
  double best_remaining = cumulative.back();
  for (std::size_t i = 0; i + 1 < path.poses.size(); ++i) {
    const auto & a = path.poses[i].pose.position;
    const auto & b = path.poses[i + 1].pose.position;
    const double dx = b.x - a.x;
    const double dy = b.y - a.y;
    const double length_squared = dx * dx + dy * dy;
    const double t = length_squared > 0.0 ? std::clamp(
      ((x - a.x) * dx + (y - a.y) * dy) / length_squared, 0.0, 1.0) : 0.0;
    const double projected_x = a.x + t * dx;
    const double projected_y = a.y + t * dy;
    const double distance_squared =
      (x - projected_x) * (x - projected_x) +
      (y - projected_y) * (y - projected_y);
    const double segment_length = std::sqrt(length_squared);
    const double candidate_remaining =
      cumulative.back() - (cumulative[i] + t * segment_length);
    if (distance_squared < best_distance_squared) {
      best_distance_squared = distance_squared;
      best_remaining = candidate_remaining;
    }
  }

  return std::max(0.0, best_remaining);
}

void AckermannSmacBridge::publishRemainingDistance()
{
  nav_msgs::msg::Path path;
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (active_path_.poses.empty()) {
      return;
    }
    path = active_path_;
  }

  try {
    const auto pose = currentRobotPose();
    std_msgs::msg::Float64 message;
    message.data = remainingDistance(
      path, pose.pose.position.x, pose.pose.position.y);
    remaining_distance_pub_->publish(message);
  } catch (const tf2::TransformException & ex) {
    RCLCPP_WARN_THROTTLE(
      get_logger(), *get_clock(), 5000,
      "Cannot compute remaining path distance: %s", ex.what());
  }
}

}  // namespace smac_neupan_bridge

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<smac_neupan_bridge::AckermannSmacBridge>());
  rclcpp::shutdown();
  return 0;
}
