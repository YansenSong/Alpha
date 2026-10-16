# ----------------------------------------#
# Hesai Tech <http://www.hesaitech.com>  #
# ----------------------------------------#

cmake_minimum_required(VERSION 3.5)
project(CommonModules)

# C++ 标准设置
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# CMake 策略
if(POLICY CMP0074)
    cmake_policy(SET CMP0074 NEW)
else(POLICY CMP0074)
    cmake_policy(SET CMP0065 NEW)
endif(POLICY CMP0074)

# ============================================
# 构建选项
# ============================================
option(WITH_LIDARBOARD "Build lidar board code" ON)
option(WITH_UDPPARSER "Build UDP parser code" ON)
option(WITH_SERIALCLIENT "Build serial client code" ON)
option(WITH_PTCCLIENT "Build PTC client code" ON)

# 自动启用 lidar_lib
if(WITH_LIDARBOARD AND WITH_UDPPARSER AND WITH_SERIALCLIENT AND WITH_PTCCLIENT)
    set(WITH_LIDARLIB ON CACHE BOOL "Build lidar code" FORCE)
endif(WITH_LIDARBOARD AND WITH_UDPPARSER AND WITH_SERIALCLIENT AND WITH_PTCCLIENT)

# 内部版本选项

# ============================================
# CUDA 支持（可选）
# 使用父级 CMakeLists.txt 设置的 CUDA_FOUND 变量
# ============================================
if(CUDA_FOUND)
    set(WITH_UDPPARSERGPU ON CACHE BOOL "Build UdpParserGpu code" FORCE)
    message(STATUS "CUDA enabled, GPU parser will be built")
else()
    set(WITH_UDPPARSERGPU OFF)
endif()

# ============================================
# 平台特定设置
# ============================================
if(MSVC)
    add_compile_options("/source-charset:utf-8")
    set(CMAKE_GENERATOR_PLATFORM x64)
    if(WITH_PTCCLIENT AND WITH_PTCS_USE)
        set(OPENSSL_ROOT_DIR "${OPENSSL_ROOT_DIR}")
        set(OPENSSL_INCLUDE_DIR ${OPENSSL_ROOT_DIR}/include)
    endif(WITH_PTCCLIENT AND WITH_PTCS_USE)
endif(MSVC)

# ============================================
# 公共依赖
# ============================================
find_package(Threads REQUIRED)

# 公共头文件目录
include_directories(${CMAKE_CURRENT_SOURCE_DIR})

# ============================================
# 按依赖顺序添加子模块
# （被依赖的模块必须先添加）
# ============================================

# 1. 基础模块（无依赖）
message(STATUS "Adding Logger module...")
add_subdirectory(Logger)

# 2. 通用工具（依赖 Logger）
message(STATUS "Adding Common module...")
add_subdirectory(Common)

# 3. UDP 解析器（依赖 Common）
if(WITH_UDPPARSER)
    message(STATUS "Adding UdpParser module...")
    add_subdirectory(UdpParser)
    
    # GPU 解析器（依赖 UdpParser + CUDA）
    if(WITH_UDPPARSERGPU AND CUDA_FOUND)
        message(STATUS "Adding UdpParserGpu module...")
        add_subdirectory(UdpParserGpu)
    endif(WITH_UDPPARSERGPU AND CUDA_FOUND)
endif(WITH_UDPPARSER)

# 4. PTC 客户端（依赖 Common）
if(WITH_PTCCLIENT)
    message(STATUS "Adding PtcClient module...")
    add_subdirectory(PtcClient)
endif(WITH_PTCCLIENT)

# 5. SomeIP 客户端（依赖 Common，可选）

# 6. 数据源模块（依赖 Common）
if(WITH_LIDARBOARD)
    message(STATUS "Adding Source module...")
    add_subdirectory(Source)
    
    # 串口客户端（依赖 Source）
    if(WITH_SERIALCLIENT)
        message(STATUS "Adding SerialClient module...")
        add_subdirectory(SerialClient)
    endif(WITH_SERIALCLIENT)
endif(WITH_LIDARBOARD)


if(WITH_LIDARLIB)
    message(STATUS "Adding Lidar module...")
    add_subdirectory(Lidar)
endif(WITH_LIDARLIB)

# ============================================
# 构建信息摘要
# ============================================
message(STATUS "")
message(STATUS "=== Build Configuration ===")
message(STATUS "  WITH_LIDARBOARD:    ${WITH_LIDARBOARD}")
message(STATUS "  WITH_UDPPARSER:     ${WITH_UDPPARSER}")
message(STATUS "  WITH_UDPPARSERGPU:  ${WITH_UDPPARSERGPU}")
message(STATUS "  WITH_PTCCLIENT:     ${WITH_PTCCLIENT}")
message(STATUS "  WITH_PTCS_USE:      ${WITH_PTCS_USE}")
message(STATUS "  WITH_SERIALCLIENT:  ${WITH_SERIALCLIENT}")
message(STATUS "  WITH_LIDARLIB:      ${WITH_LIDARLIB}")
message(STATUS "===========================")
message(STATUS "")
