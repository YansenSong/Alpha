# ----------------------------------------#
# Hesai Tech <http://www.hesaitech.com>  #
# ----------------------------------------#
# 重构版本：只引入需要的模块

cmake_minimum_required(VERSION 3.5)
project(PtcTools)

# C++ 标准设置
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# ============================================
# 构建选项
# ============================================
option(WITH_PTCS_USE "Build with SSL support" ON)

# ============================================
# 平台特定设置
# ============================================
if(MSVC)
    add_compile_options("/source-charset:utf-8")
    set(CMAKE_GENERATOR_PLATFORM x64)
    if(WITH_PTCS_USE)
        set(OPENSSL_ROOT_DIR "${OPENSSL_ROOT_DIR}")
        set(OPENSSL_INCLUDE_DIR ${OPENSSL_ROOT_DIR}/include)
    endif(WITH_PTCS_USE)
endif(MSVC)

# ============================================
# 公共依赖
# ============================================
find_package(Threads REQUIRED)

# libhesai 路径
set(LIBHESAI_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../libhesai)

# ============================================
# 只引入需要的模块（按依赖顺序）
# ============================================

# 1. Logger (无依赖)
add_subdirectory(${LIBHESAI_DIR}/Logger ${CMAKE_CURRENT_BINARY_DIR}/Logger)

# 2. Common (依赖 Logger)
add_subdirectory(${LIBHESAI_DIR}/Common ${CMAKE_CURRENT_BINARY_DIR}/Common)

# 3. PtcClient (依赖 Common)
add_subdirectory(${LIBHESAI_DIR}/PtcClient ${CMAKE_CURRENT_BINARY_DIR}/PtcClient)

# ============================================
# 可执行文件
# ============================================

# ptc_upgrade 工具
add_executable(ptc_upgrade
    ptc_upgrade.cc
)
target_link_libraries(ptc_upgrade PRIVATE
    ptcClient_lib
)

# ptc_tool 工具
add_executable(ptc_tool
    ptc_tool.cc
)
target_link_libraries(ptc_tool PRIVATE
    ptcClient_lib
)

# ============================================
# 构建信息
# ============================================
message(STATUS "")
message(STATUS "=== PtcTools Build Configuration ===")
message(STATUS "  WITH_PTCS_USE: ${WITH_PTCS_USE}")
message(STATUS "====================================")
