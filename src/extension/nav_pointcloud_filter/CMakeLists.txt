cmake_minimum_required(VERSION 3.10)
project(nav_pointcloud_filter)

find_package(ament_cmake REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_ros REQUIRED)

add_executable(self_filter_node src/self_filter_node.cpp)
ament_target_dependencies(self_filter_node geometry_msgs rclcpp sensor_msgs tf2 tf2_ros)
target_compile_features(self_filter_node PUBLIC cxx_std_17)

install(TARGETS self_filter_node DESTINATION lib/${PROJECT_NAME})
ament_package()
