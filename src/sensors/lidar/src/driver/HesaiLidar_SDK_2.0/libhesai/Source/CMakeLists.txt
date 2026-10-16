# Source module
# 依赖: platutils_lib

add_library(source_lib STATIC
    src/source.cc
    src/socket_source.cc
    src/pcap_source.cc
    src/serial_source.cc
    src/pcap_saver.cc
    src/tcp_source.cc
)

target_include_directories(source_lib PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../Container/include>
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../Container/src>
)

target_link_libraries(source_lib PUBLIC
    platutils_lib
)

set_target_properties(source_lib PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
)
