cmake_minimum_required(VERSION 3.8)
project(nav_status)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(rclcpp REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(nav_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(nlohmann_json REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/NavigationStatus.msg"
  "msg/NavigationExecution.msg"
  "msg/ControllerFeedback.msg"
  DEPENDENCIES builtin_interfaces geometry_msgs
)

add_executable(nav_status_node
  src/nav_status_node.cpp
)

ament_target_dependencies(nav_status_node
  rclcpp
  geometry_msgs
  nav_msgs
  std_msgs
  builtin_interfaces
)

rosidl_get_typesupport_target(cpp_typesupport_target ${PROJECT_NAME} "rosidl_typesupport_cpp")
target_link_libraries(nav_status_node "${cpp_typesupport_target}" nlohmann_json::nlohmann_json)
add_dependencies(nav_status_node ${PROJECT_NAME}__rosidl_generator_cpp)
install(TARGETS nav_status_node
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY config
  DESTINATION share/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(execution_contract test/test_execution_contract.py
    TIMEOUT 90 APPEND_ENV ROS_DOMAIN_ID=187)
endif()

ament_export_dependencies(rosidl_default_runtime)
ament_package()
