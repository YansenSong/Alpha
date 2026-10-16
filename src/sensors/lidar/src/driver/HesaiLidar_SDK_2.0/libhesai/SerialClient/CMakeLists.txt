# SerialClient module
# 依赖: source_lib

add_library(serialClient_lib STATIC
    src/serial_client.cc
)

target_include_directories(serialClient_lib PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)

target_link_libraries(serialClient_lib PUBLIC
    source_lib
)

set_target_properties(serialClient_lib PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
)
