# ----------------------------------------#
# Hesai Tech <http://www.hesaitech.com>  #
# ----------------------------------------#

cmake_minimum_required(VERSION 3.8.11)
project(SDKTool)

# ============================================
# C++ 标准设置
# ============================================
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ============================================
# CMake 策略
# ============================================
cmake_policy(SET CMP0053 NEW)

# ============================================
# 构建类型设置
# ============================================
set(CMAKE_BUILD_TYPE Release)
add_definitions(-O3)
add_compile_options($<$<COMPILE_LANGUAGE:CXX>:-Wall> $<$<COMPILE_LANGUAGE:C>:-Wall>)

# ============================================
# 平台特定设置
# ============================================
if(MSVC)
    set(CMAKE_GENERATOR_PLATFORM x64)
endif(MSVC)

# ============================================
# CUDA 支持
# ============================================
if(FIND_CUDA)
    find_package(CUDA)
    if(CUDA_FOUND)
        project(SDKTool LANGUAGES CXX CUDA)
        set(CUDA_SOURCE_PROPERTY_FORMAT OBJ)
        set(CUDA_SEPARABLE_COMPILATION ON)
        include_directories(${CUDA_INCLUDE_DIRS})
        set(CUDA_PROPAGATE_HOST_FLAGS OFF)
        set(CUDA_NVCC_FLAGS -arch=sm_61;-O3;-G;-g;-std=c++17)
        link_directories($ENV{CUDA_PATH}/lib/x64)
        add_definitions(-DUSE_CUDA)
        message(STATUS "CUDA found, GPU support enabled")
    else(CUDA_FOUND)
        message(STATUS "CUDA not found!")
    endif(CUDA_FOUND)
endif(FIND_CUDA)

# ============================================
# 内部版本配置
# ============================================


# ============================================
# 添加 SDK 子模块
# ============================================
set(DISENABLE_TEST_CC ON CACHE BOOL "Disable test executables" FORCE)

include_directories("${PROJECT_BINARY_DIR}")
add_subdirectory(../ ${CMAKE_CURRENT_BINARY_DIR}/Hesai_lidar_sdk)

# ============================================
# 工具: pcl_tool (依赖 PCL)
# ============================================
find_package(PCL COMPONENTS common visualization io QUIET REQUIRED)

if(PCL_FOUND)
    add_executable(pcl_tool
        pcl_tool.cc
    )

    target_include_directories(pcl_tool PRIVATE
        ${PCL_INCLUDE_DIRS}
    )

    target_link_directories(pcl_tool PRIVATE
        ${PCL_LIBRARY_DIRS}
    )

    target_link_libraries(pcl_tool PRIVATE
        hesai_sdk_lib
        ${PCL_LIBRARIES}
    )
    message(STATUS "PCL found, pcl_tool will be built")
else()
    message(STATUS "PCL not found, pcl_tool will be skipped")
    message(STATUS "  Debian/Ubuntu: sudo apt install libpcl-dev")
    message(STATUS "  Or set PCL_DIR to the directory containing PCLConfig.cmake, or add PCL install prefix to CMAKE_PREFIX_PATH")
endif()

# ============================================
# 工具: las_tool (依赖 LASlib，可选)
# ============================================
find_package(LASlib QUIET)

if(LASlib_FOUND)
    add_executable(las_tool
        las_tool.cc
    )

    target_include_directories(las_tool PRIVATE
        ${LASlib_INCLUDE_DIRS}
    )

    target_link_directories(las_tool PRIVATE
        ${LASlib_LIBRARY_DIRS}
    )

    target_link_libraries(las_tool PRIVATE
        hesai_sdk_lib
        LASlib
        ${PCL_LIBRARIES}
    )
    
    message(STATUS "LASlib found, las_tool will be built")
else(LASlib_FOUND)
    message(STATUS "LASlib not found, las_tool will be skipped")
endif(LASlib_FOUND)

# ============================================
# 构建信息摘要
# ============================================
message(STATUS "")
message(STATUS "=== SDKTool Build Configuration ===")
message(STATUS "  FIND_CUDA:      ${FIND_CUDA}")
message(STATUS "  CUDA_FOUND:     ${CUDA_FOUND}")
message(STATUS "  PCL_FOUND:      ${PCL_FOUND}")
message(STATUS "  LASlib_FOUND:   ${LASlib_FOUND}")
message(STATUS "===================================")
message(STATUS "")
