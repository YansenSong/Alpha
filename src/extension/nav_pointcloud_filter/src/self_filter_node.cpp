#include <cmath>
#include <cstdint>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <string>

#include "geometry_msgs/msg/transform_stamped.hpp"
#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/point_cloud2.hpp"
#include "sensor_msgs/msg/point_field.hpp"
#include "tf2/LinearMath/Quaternion.h"
#include "tf2/LinearMath/Transform.h"
#include "tf2_ros/buffer.h"
#include "tf2_ros/transform_listener.h"

class SelfFilterNode : public rclcpp::Node
{
public:
  SelfFilterNode()
  : Node("nav_self_filter"), tf_buffer_(this->get_clock()), tf_listener_(tf_buffer_)
  {
    base_frame_ = declare_parameter<std::string>("base_frame", "rear_axle_link");
    front_ = declare_parameter<double>("front_extent", 0.0);
    rear_ = declare_parameter<double>("rear_extent", 0.0);
    half_width_ = declare_parameter<double>("half_width", 0.0);
    inset_ = declare_parameter<double>("xy_inset", 0.02);
    min_z_ = declare_parameter<double>("min_z", -0.05);
    max_z_ = declare_parameter<double>("max_z", 0.0);
    if (base_frame_.empty() || !std::isfinite(front_) || !std::isfinite(rear_) ||
      !std::isfinite(half_width_) || !std::isfinite(inset_) ||
      !std::isfinite(min_z_) || !std::isfinite(max_z_) || front_ <= inset_ ||
      rear_ <= inset_ || half_width_ <= inset_ || inset_ < 0.0 || min_z_ >= max_z_)
    {
      throw std::invalid_argument("Invalid navigation self-filter body bounds");
    }

    auto qos = rclcpp::SensorDataQoS();
    publisher_ = create_publisher<sensor_msgs::msg::PointCloud2>("points_out", qos);
    subscription_ = create_subscription<sensor_msgs::msg::PointCloud2>(
      "points_in", qos,
      [this](sensor_msgs::msg::PointCloud2::ConstSharedPtr cloud) { filter(cloud); });
  }

private:
  static bool xyz_offsets(
    const sensor_msgs::msg::PointCloud2 & cloud, uint32_t & x, uint32_t & y, uint32_t & z)
  {
    bool has_x = false, has_y = false, has_z = false;
    for (const auto & field : cloud.fields) {
      if (field.datatype != sensor_msgs::msg::PointField::FLOAT32 || field.count != 1 ||
        field.offset > cloud.point_step || cloud.point_step - field.offset < sizeof(float))
      {
        continue;
      }
      if (field.name == "x") {x = field.offset; has_x = true;}
      if (field.name == "y") {y = field.offset; has_y = true;}
      if (field.name == "z") {z = field.offset; has_z = true;}
    }
    return has_x && has_y && has_z;
  }

  static float read_float(const uint8_t * data, uint32_t offset)
  {
    float value;
    std::memcpy(&value, data + offset, sizeof(value));
    return value;
  }

  void filter(const sensor_msgs::msg::PointCloud2::ConstSharedPtr & cloud)
  {
    uint32_t x_offset = 0, y_offset = 0, z_offset = 0;
    if (cloud->point_step == 0 || !xyz_offsets(*cloud, x_offset, y_offset, z_offset) ||
      cloud->is_bigendian || cloud->row_step < cloud->width * cloud->point_step ||
      cloud->data.size() < static_cast<size_t>(cloud->height) * cloud->row_step)
    {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000,
        "Invalid or unsupported PointCloud2 layout; dropping navigation cloud");
      return;
    }

    geometry_msgs::msg::TransformStamped stamped;
    try {
      stamped = tf_buffer_.lookupTransform(
        base_frame_, cloud->header.frame_id, cloud->header.stamp,
        rclcpp::Duration::from_seconds(0.05));
    } catch (const tf2::TransformException & ex) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000,
        "Cannot transform navigation cloud into %s: %s", base_frame_.c_str(), ex.what());
      return;
    }

    const auto & t = stamped.transform.translation;
    const auto & q = stamped.transform.rotation;
    tf2::Transform to_base(tf2::Quaternion(q.x, q.y, q.z, q.w), tf2::Vector3(t.x, t.y, t.z));

    auto output = std::make_unique<sensor_msgs::msg::PointCloud2>();
    output->header = cloud->header;
    output->fields = cloud->fields;
    output->is_bigendian = cloud->is_bigendian;
    output->point_step = cloud->point_step;
    output->height = 1;
    output->is_dense = true;
    output->data.reserve(cloud->data.size());

    for (uint32_t row = 0; row < cloud->height; ++row) {
      for (uint32_t col = 0; col < cloud->width; ++col) {
        const auto * point = cloud->data.data() + row * cloud->row_step + col * cloud->point_step;
        const float x = read_float(point, x_offset);
        const float y = read_float(point, y_offset);
        const float z = read_float(point, z_offset);
        if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z)) {continue;}

        const tf2::Vector3 body = to_base * tf2::Vector3(x, y, z);
        const bool is_body =
          body.x() > -rear_ + inset_ && body.x() < front_ - inset_ &&
          std::abs(body.y()) < half_width_ - inset_ &&
          body.z() >= min_z_ && body.z() <= max_z_;
        if (is_body) {continue;}
        output->data.insert(output->data.end(), point, point + cloud->point_step);
      }
    }
    output->width = static_cast<uint32_t>(output->data.size() / output->point_step);
    output->row_step = output->width * output->point_step;
    publisher_->publish(std::move(output));
  }

  std::string base_frame_;
  double front_, rear_, half_width_, inset_, min_z_, max_z_;
  tf2_ros::Buffer tf_buffer_;
  tf2_ros::TransformListener tf_listener_;
  rclcpp::Publisher<sensor_msgs::msg::PointCloud2>::SharedPtr publisher_;
  rclcpp::Subscription<sensor_msgs::msg::PointCloud2>::SharedPtr subscription_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<SelfFilterNode>());
  rclcpp::shutdown();
  return 0;
}
