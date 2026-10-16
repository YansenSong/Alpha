cmake_minimum_required(VERSION 3.8)
project(nav_neupan_bringup)

find_package(ament_cmake REQUIRED)

install(DIRECTORY config launch rviz DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(rules_launch test/test_rules_launch.py)
endif()

ament_package()
