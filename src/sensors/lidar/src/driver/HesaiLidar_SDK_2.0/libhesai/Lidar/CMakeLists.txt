# Lidar module - 聚合所有组件的主库（纯头文件模板库）
# 依赖: 所有其他模块

add_library(lidar_lib INTERFACE)

target_include_directories(lidar_lib INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/..>
)

# 核心依赖
target_link_libraries(lidar_lib INTERFACE
    log_lib
    platutils_lib
    udpParser_lib
    ptcClient_lib
    source_lib
    serialClient_lib
    Threads::Threads
)

# GPU 支持（可选）
if(WITH_UDPPARSERGPU AND TARGET udpParserGpu_lib)
    target_link_libraries(lidar_lib INTERFACE udpParserGpu_lib)
endif(WITH_UDPPARSERGPU AND TARGET udpParserGpu_lib)

# 条件编译定义
