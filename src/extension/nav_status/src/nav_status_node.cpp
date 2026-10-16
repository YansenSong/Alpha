#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>

#include "geometry_msgs/msg/pose_stamped.hpp"
#include "nav_msgs/msg/odometry.hpp"
#include "nav_msgs/msg/path.hpp"
#include "rclcpp/rclcpp.hpp"
#include "std_msgs/msg/bool.hpp"
#include "std_msgs/msg/string.hpp"

#include "nav_status/msg/navigation_status.hpp"

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
    plan_topic_ = declare_parameter<std::string>("plan_topic", "/plan_path");
    odom_topic_ = declare_parameter<std::string>("odom_topic", "/odom_wheel");
    status_topic_ = declare_parameter<std::string>("status_topic", "/navigation/state");
    planning_status_topic_ = declare_parameter<std::string>(
      "planning_status_topic", "/global_plan/status");
    arrival_topic_ = declare_parameter<std::string>("arrival_topic", "/neupan/arrived");

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
    plan_sub_ = create_subscription<nav_msgs::msg::Path>(
      plan_topic_, input_qos,
      std::bind(&NavStatusNode::onPlan, this, std::placeholders::_1));
    odom_sub_ = create_subscription<nav_msgs::msg::Odometry>(
      odom_topic_, input_qos,
      std::bind(&NavStatusNode::onOdom, this, std::placeholders::_1));
    planning_status_sub_ = create_subscription<std_msgs::msg::String>(
      planning_status_topic_, input_qos,
      std::bind(&NavStatusNode::onPlanningStatus, this, std::placeholders::_1));
    arrival_sub_ = create_subscription<std_msgs::msg::Bool>(
      arrival_topic_, input_qos,
      std::bind(&NavStatusNode::onArrival, this, std::placeholders::_1));

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

  void onGoal(const geometry_msgs::msg::PoseStamped::SharedPtr /*msg*/)
  {
    arrival_candidate_since_.reset();

    // Do not reuse telemetry from the previous navigation task.
    actual_speed_.reset();
    odom_stamp_.reset();
    neupan_arrived_ = false;
    arrival_stamp_.reset();
    state_entered_at_ = now();
    rule_replan_pending_ = false;

    transitionTo(State::PLANNING, "new goal received; waiting for global plan");
  }

  void onPlanningStatus(const std_msgs::msg::String::SharedPtr msg)
  {
    if (msg->data == "rule_replan_pending") {
      rule_replan_pending_ = true;
      transitionTo(State::PLANNING, "rule_replan_pending; vehicle held");
      return;
    }
    if (msg->data == "planning") {
      return;
    }
    if (msg->data == "succeeded") {
      rule_replan_pending_ = false;
      if (state_ == State::PLANNING) {
        state_entered_at_ = now();
        transitionTo(State::MOVING, "global plan available; navigation active");
      }
      return;
    }
    if (msg->data.rfind("failed:", 0) == 0 && state_ == State::PLANNING) {
      transitionTo(State::FAILED, msg->data);
    }
  }

  void onArrival(const std_msgs::msg::Bool::SharedPtr msg)
  {
    neupan_arrived_ = msg->data;
    arrival_stamp_ = now();
  }

  void onPlan(const nav_msgs::msg::Path::SharedPtr msg)
  {
    (void)msg;  // Execution begins only after the controller installs the validated path.
  }

  void onOdom(const nav_msgs::msg::Odometry::SharedPtr msg)
  {
    const double speed = std::hypot(
      msg->twist.twist.linear.x,
      msg->twist.twist.linear.y);
    if (!std::isfinite(speed)) {
      return;
    }

    actual_speed_ = speed;
    odom_stamp_ = now();
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
      transitionTo(State::ARRIVED, "goal reached and vehicle stopped");
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
  }

  State state_;
  std::string detail_;

  std::optional<double> actual_speed_;
  std::optional<rclcpp::Time> odom_stamp_;
  std::optional<rclcpp::Time> arrival_candidate_since_;
  std::optional<rclcpp::Time> arrival_stamp_;
  std::optional<rclcpp::Time> state_entered_at_;
  bool neupan_arrived_{false};
  bool rule_replan_pending_{false};

  rclcpp::Subscription<geometry_msgs::msg::PoseStamped>::SharedPtr goal_sub_;
  rclcpp::Subscription<nav_msgs::msg::Path>::SharedPtr plan_sub_;
  rclcpp::Subscription<nav_msgs::msg::Odometry>::SharedPtr odom_sub_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr planning_status_sub_;
  rclcpp::Subscription<std_msgs::msg::Bool>::SharedPtr arrival_sub_;
  rclcpp::Publisher<NavigationStatus>::SharedPtr status_pub_;
  rclcpp::TimerBase::SharedPtr evaluation_timer_;
  rclcpp::TimerBase::SharedPtr heartbeat_timer_;

  std::string goal_topic_;
  std::string plan_topic_;
  std::string odom_topic_;
  std::string status_topic_;
  std::string planning_status_topic_;
  std::string arrival_topic_;

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
