#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <functional>
#include <memory>
#include <map>
#include <optional>
#include <string>

#include "geometry_msgs/msg/pose_stamped.hpp"
#include "nav_msgs/msg/odometry.hpp"
#include "nav_msgs/msg/path.hpp"
#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/bool.hpp"
#include "std_msgs/msg/string.hpp"

#include "nav_status/msg/navigation_status.hpp"
#include "nav_status/msg/navigation_execution.hpp"
#include "nav_status/msg/controller_feedback.hpp"
#include <nlohmann/json.hpp>

namespace nav_status
{

class NavStatusNode : public rclcpp::Node
{
public:
  using NavigationStatus = nav_status::msg::NavigationStatus;

  enum class State : std::uint8_t
  {
    WAITING_FOR_GOAL = NavigationStatus::WAITING_FOR_GOAL,
    PLANNING = NavigationStatus::PLANNING,
    MOVING = NavigationStatus::MOVING,
    ARRIVED = NavigationStatus::ARRIVED,
    FAILED = NavigationStatus::FAILED,
  };

  explicit NavStatusNode(const rclcpp::NodeOptions & options = rclcpp::NodeOptions())
  : Node("nav_status_node", options), state_(State::WAITING_FOR_GOAL)
  {
    goal_topic_ = declare_parameter<std::string>("goal_topic", "/goal_pose");
    odom_topic_ = declare_parameter<std::string>("odom_topic", "/odom_wheel");
    status_topic_ = declare_parameter<std::string>("status_topic", "/navigation/state");

    stopped_speed_threshold_ = declare_parameter<double>(
      "stopped_speed_threshold", 0.05);
    arrival_hold_time_ = declare_parameter<double>("arrival_hold_time", 0.80);
    input_timeout_ = declare_parameter<double>("input_timeout", 2.0);
    planning_timeout_ = declare_parameter<double>("planning_timeout", 10.0);
    evaluation_rate_ = declare_parameter<double>("evaluation_rate", 20.0);
    status_heartbeat_rate_ = declare_parameter<double>("status_heartbeat_rate", 1.0);

    if (stopped_speed_threshold_ < 0.0) {
      RCLCPP_WARN(this->get_logger(),
        "stopped_speed_threshold must be non-negative; using 0.05 m/s");
      stopped_speed_threshold_ = 0.05;
    }
    if (arrival_hold_time_ < 0.0) {
      RCLCPP_WARN(this->get_logger(),
        "arrival_hold_time must be non-negative; using 0.80 s");
      arrival_hold_time_ = 0.80;
    }
    if (input_timeout_ <= 0.0) {
      RCLCPP_WARN(this->get_logger(),
        "input_timeout must be positive; using 2.0 s");
      input_timeout_ = 2.0;
    }
    if (planning_timeout_ <= 0.0) {
      RCLCPP_WARN(this->get_logger(),
        "planning_timeout must be positive; using 10.0 s");
      planning_timeout_ = 10.0;
    }
    if (evaluation_rate_ <= 0.0) {
      RCLCPP_WARN(this->get_logger(),
        "evaluation_rate must be positive; using 20.0 Hz");
      evaluation_rate_ = 20.0;
    }
    if (status_heartbeat_rate_ < 0.0) {
      RCLCPP_WARN(this->get_logger(),
        "status_heartbeat_rate must be non-negative; disabling heartbeat");
      status_heartbeat_rate_ = 0.0;
    }

    auto status_qos = rclcpp::QoS(rclcpp::KeepLast(1));
    status_qos.reliable();
    status_qos.transient_local();
    status_pub_ = create_publisher<NavigationStatus>(status_topic_, status_qos);

    const auto input_qos = rclcpp::QoS(rclcpp::KeepLast(10)).reliable();
    goal_sub_ = create_subscription<geometry_msgs::msg::PoseStamped>(
      goal_topic_, input_qos,
      std::bind(&NavStatusNode::onGoal, this, std::placeholders::_1));
    execution_pub_ = create_publisher<nav_status::msg::NavigationExecution>(
      "/navigation/execution_state", status_qos);
    planner_sub_ = create_subscription<nav_status::msg::NavigationExecution>(
      "/navigation/planner_state", status_qos,
      std::bind(&NavStatusNode::onPlanner, this, std::placeholders::_1));
    odom_sub_ = create_subscription<nav_msgs::msg::Odometry>(
      odom_topic_, input_qos,
      std::bind(&NavStatusNode::onOdom, this, std::placeholders::_1));
    feedback_sub_ = create_subscription<nav_status::msg::ControllerFeedback>(
      "/neupan/controller_feedback", input_qos,
      std::bind(&NavStatusNode::onFeedback, this, std::placeholders::_1));

    evaluation_timer_ = create_wall_timer(
      periodFromRate(evaluation_rate_),
      std::bind(&NavStatusNode::evaluateArrival, this));
    if (status_heartbeat_rate_ > 0.0) {
      heartbeat_timer_ = create_wall_timer(
        periodFromRate(status_heartbeat_rate_),
        std::bind(&NavStatusNode::publishStatus, this));
    }

    detail_ = "node started; waiting for goal";
    publishStatus();
  }

private:
  static std::chrono::milliseconds periodFromRate(const double rate)
  {
    const auto period_ms = static_cast<std::int64_t>(std::ceil(1000.0 / rate));
    return std::chrono::milliseconds(std::max<std::int64_t>(1, period_ms));
  }

  static const char * stateName(const State state)
  {
    switch (state) {
      case State::WAITING_FOR_GOAL:
        return "WAITING_FOR_GOAL";
      case State::PLANNING:
        return "PLANNING";
      case State::MOVING:
        return "MOVING";
      case State::ARRIVED:
        return "ARRIVED";
      case State::FAILED:
        return "FAILED";
    }
    return "UNKNOWN";
  }

  static bool sameGoal(const geometry_msgs::msg::PoseStamped & a,
                       const geometry_msgs::msg::PoseStamped & b)
  {
    return a.header.stamp == b.header.stamp && a.header.frame_id == b.header.frame_id &&
      a.pose == b.pose;
  }

  void onGoal(const geometry_msgs::msg::PoseStamped::SharedPtr msg)
  {
    if (have_goal_ && sameGoal(goal_, *msg)) {return;}
    goal_ = *msg;
    have_goal_ = true;
    execution_id_ = std::to_string(goal_.header.stamp.sec) + ":" +
      std::to_string(goal_.header.stamp.nanosec);
    path_stamp_ = builtin_interfaces::msg::Time();
    result_json_.clear();
    planner_stamp_.reset();
    arrival_candidate_since_.reset();

    // Do not reuse telemetry from the previous navigation task.
    actual_speed_.reset();
    odom_stamp_.reset();
    neupan_arrived_ = false;
    arrival_stamp_.reset();
    state_entered_at_ = now();
    rule_replan_pending_ = false;

    transitionTo(State::PLANNING, "new goal received; waiting for global plan");
    const auto key = rclcpp::Time(goal_.header.stamp).nanoseconds();
    const auto pending = pending_planners_.find(key);
    if (pending != pending_planners_.end()) {
      auto event = std::make_shared<nav_status::msg::NavigationExecution>(pending->second);
      pending_planners_.erase(pending);
      onPlanner(event);
    }
  }

  void onPlanner(const nav_status::msg::NavigationExecution::SharedPtr msg)
  {
    // Goal stamps are identities, not an ordering clock: Web and ROS clients
    // may use different time domains. Only /goal_pose starts an execution.
    // Buffer a bounded number of planner events for cross-publisher ordering.
    if (!have_goal_ || !sameGoal(goal_, msg->goal)) {
      pending_planners_[rclcpp::Time(msg->goal.header.stamp).nanoseconds()] = *msg;
      if (pending_planners_.size() > 8) {pending_planners_.erase(pending_planners_.begin());}
      return;
    }
    if (state_ == State::ARRIVED || state_ == State::FAILED) {return;}
    if (planner_stamp_ && rclcpp::Time(msg->stamp) < *planner_stamp_) {return;}
    planner_stamp_ = rclcpp::Time(msg->stamp);
    rule_replan_pending_ = msg->held;
    if (msg->state == msg->FAILED) {
      transitionTo(State::FAILED, msg->detail);
    } else if (msg->state == msg->MOVING) {
      if (msg->path_stamp.sec == 0 && msg->path_stamp.nanosec == 0) {return;}
      if (path_stamp_ != msg->path_stamp) {
        neupan_arrived_ = false;
        arrival_stamp_.reset();
        arrival_candidate_since_.reset();
      }
      path_stamp_ = msg->path_stamp;
      state_entered_at_ = now();
      transitionTo(State::MOVING, "controller installed current execution path");
    } else {
      arrival_candidate_since_.reset();
      transitionTo(State::PLANNING, msg->detail);
    }
  }

  void onFeedback(const nav_status::msg::ControllerFeedback::SharedPtr msg)
  {
    if (state_ != State::MOVING || msg->path_stamp != path_stamp_) {return;}
    const double age = (now() - rclcpp::Time(msg->stamp)).seconds();
    const double pose_age = (now() - rclcpp::Time(msg->observed_pose.header.stamp)).seconds();
    const auto & p = msg->observed_pose.pose;
    if (pose_age < 0.0 || pose_age > input_timeout_ ||
        msg->observed_pose.header.frame_id.empty() ||
        !std::isfinite(p.position.x) || !std::isfinite(p.position.y)) {return;}
    if (age < 0.0 || age > input_timeout_ || !std::isfinite(msg->position_tolerance) ||
        msg->position_tolerance <= 0.0) {return;}
    if (arrival_stamp_ && rclcpp::Time(msg->stamp) < *arrival_stamp_) {return;}
    neupan_arrived_ = msg->arrived;
    arrival_stamp_ = rclcpp::Time(msg->stamp);
    feedback_ = *msg;
  }

  void onOdom(const nav_msgs::msg::Odometry::SharedPtr msg)
  {
    const double speed = std::hypot(
      msg->twist.twist.linear.x,
      msg->twist.twist.linear.y);
    if (!std::isfinite(speed)) {
      return;
    }

    const double age = (now() - rclcpp::Time(msg->header.stamp)).seconds();
    if (age < 0.0 || age > input_timeout_) {return;}
    if (odom_stamp_ && rclcpp::Time(msg->header.stamp) < *odom_stamp_) {return;}
    actual_speed_ = speed;
    odom_stamp_ = rclcpp::Time(msg->header.stamp);
  }

  bool isFresh(const std::optional<rclcpp::Time> & stamp, const rclcpp::Time & current) const
  {
    if (!stamp) {
      return false;
    }

    const double age = (current - *stamp).seconds();
    return age >= 0.0 && age <= input_timeout_;
  }

  void evaluateArrival()
  {
    const auto current = now();
    if (state_ == State::PLANNING) {
      if (!rule_replan_pending_ && state_entered_at_ &&
        (current - *state_entered_at_).seconds() > planning_timeout_)
      {
        transitionTo(State::FAILED, "failed: global planning timed out");
      }
      return;
    }

    if (state_ != State::MOVING) {
      arrival_candidate_since_.reset();
      return;
    }

    const bool odom_fresh = actual_speed_ && isFresh(odom_stamp_, current);
    const bool arrival_fresh = arrival_stamp_ && isFresh(arrival_stamp_, current);
    if (!odom_fresh || !arrival_fresh)
    {
      arrival_candidate_since_.reset();
      if (state_entered_at_ &&
        (current - *state_entered_at_).seconds() > input_timeout_)
      {
        transitionTo(
          State::FAILED,
          !odom_fresh ? "failed: odometry input timed out" :
          "failed: NeuPAN arrival input timed out");
      }
      return;
    }

    const bool stopped = *actual_speed_ <= stopped_speed_threshold_;
    if (!neupan_arrived_ || !stopped) {
      arrival_candidate_since_.reset();
      return;
    }

    if (!arrival_candidate_since_) {
      arrival_candidate_since_ = current;
      return;
    }

    if ((current - *arrival_candidate_since_).seconds() >= arrival_hold_time_) {
      using nlohmann::json;
      const auto & p = feedback_.observed_pose.pose;
      const auto & target = goal_.pose;
      result_json_ = json({
        {"source", "nav_status"}, {"policy_version", 1}, {"verified", true},
        {"execution_id", execution_id_},
        {"goal_stamp_ns", rclcpp::Time(goal_.header.stamp).nanoseconds()},
        {"path_stamp_ns", rclcpp::Time(path_stamp_).nanoseconds()},
        {"target", {{"x", target.position.x}, {"y", target.position.y},
                    {"z", target.orientation.z}, {"w", target.orientation.w}}},
        {"observed_pose", {{"x", p.position.x}, {"y", p.position.y},
                           {"z", p.orientation.z}, {"w", p.orientation.w}}},
        {"pose_frame", feedback_.observed_pose.header.frame_id},
        {"position_tolerance", feedback_.position_tolerance},
        {"linear_speed", *actual_speed_}, {"stopped_speed_threshold", stopped_speed_threshold_},
        {"stable_stop_seconds", (current - *arrival_candidate_since_).seconds()},
        {"arrival_hold_time", arrival_hold_time_},
        {"observed_stamp_ns", rclcpp::Time(feedback_.stamp).nanoseconds()},
        {"pose_stamp_ns", rclcpp::Time(feedback_.observed_pose.header.stamp).nanoseconds()},
        {"odometry_topic", odom_topic_},
        {"odometry_stamp_ns", rclcpp::Time(*odom_stamp_).nanoseconds()}
      }).dump();
      transitionTo(State::ARRIVED, "controller reached endpoint and vehicle stopped");
      arrival_candidate_since_.reset();
    }
  }

  void transitionTo(const State next, const std::string & detail)
  {
    const State previous = state_;
    const bool changed = previous != next;
    state_ = next;
    detail_ = detail;

    if (changed) {
      RCLCPP_INFO(this->get_logger(),
        "Navigation state: %s -> %s",
        stateName(previous), stateName(next));
    }

    // A new goal can arrive while already in PLANNING.  Republish in that
    // case so consumers can observe the new task even without a state change.
    publishStatus();
  }

  void publishStatus()
  {
    NavigationStatus status;
    status.stamp = now();
    status.state = static_cast<std::uint8_t>(state_);
    status.detail = detail_;
    status_pub_->publish(status);
    nav_status::msg::NavigationExecution execution;
    execution.stamp = status.stamp;
    execution.goal = goal_;
    execution.path_stamp = path_stamp_;
    execution.execution_id = execution_id_;
    execution.state = status.state;
    execution.held = rule_replan_pending_;
    execution.detail = detail_;
    execution.result_json = result_json_;
    execution_pub_->publish(execution);
  }

  std::map<std::int64_t, nav_status::msg::NavigationExecution> pending_planners_;
  bool have_goal_{false};
  geometry_msgs::msg::PoseStamped goal_;
  builtin_interfaces::msg::Time path_stamp_;
  nav_status::msg::ControllerFeedback feedback_;
  std::string execution_id_, result_json_;
  rclcpp::Publisher<nav_status::msg::NavigationExecution>::SharedPtr execution_pub_;
  rclcpp::Subscription<nav_status::msg::NavigationExecution>::SharedPtr planner_sub_;
  rclcpp::Subscription<nav_status::msg::ControllerFeedback>::SharedPtr feedback_sub_;
  State state_;
  std::string detail_;

  std::optional<rclcpp::Time> planner_stamp_;
  std::optional<double> actual_speed_;
  std::optional<rclcpp::Time> odom_stamp_;
  std::optional<rclcpp::Time> arrival_candidate_since_;
  std::optional<rclcpp::Time> arrival_stamp_;
  std::optional<rclcpp::Time> state_entered_at_;
  bool neupan_arrived_{false};
  bool rule_replan_pending_{false};

  rclcpp::Subscription<geometry_msgs::msg::PoseStamped>::SharedPtr goal_sub_;
  rclcpp::Subscription<nav_msgs::msg::Odometry>::SharedPtr odom_sub_;
  rclcpp::Publisher<NavigationStatus>::SharedPtr status_pub_;
  rclcpp::TimerBase::SharedPtr evaluation_timer_;
  rclcpp::TimerBase::SharedPtr heartbeat_timer_;

  std::string goal_topic_;
  std::string odom_topic_;
  std::string status_topic_;

  double stopped_speed_threshold_ = 0.05;
  double arrival_hold_time_ = 0.80;
  double input_timeout_ = 2.0;
  double planning_timeout_ = 10.0;
  double evaluation_rate_ = 20.0;
  double status_heartbeat_rate_ = 1.0;
};

}  // namespace nav_status

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<nav_status::NavStatusNode>());
  rclcpp::shutdown();
  return 0;
}
