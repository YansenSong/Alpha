cmake_minimum_required(VERSION 3.10)
project(pcd2gridmap)

find_package(PCL 1.10 REQUIRED COMPONENTS common io filters segmentation)

include_directories(${PCL_INCLUDE_DIRS})
link_directories(${PCL_LIBRARY_DIRS})
add_definitions(${PCL_DEFINITIONS})

add_executable(pcd2gridmap pcd2gridmap.cpp)
target_link_libraries(pcd2gridmap ${PCL_LIBRARIES})
