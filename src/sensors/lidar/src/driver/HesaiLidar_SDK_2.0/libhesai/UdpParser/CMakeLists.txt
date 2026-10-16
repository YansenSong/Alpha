# UdpParser module（纯头文件模板库）
# 依赖: log_lib, platutils_lib

add_library(udpParser_lib INTERFACE)

target_include_directories(udpParser_lib INTERFACE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../UdpProtocol>
)

target_link_libraries(udpParser_lib INTERFACE
    log_lib
    platutils_lib
)
