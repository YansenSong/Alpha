# Common/PlatUtils module
# 依赖: log_lib

add_library(platutils_lib STATIC
    src/plat_utils.cc
    src/auto_tick_count.cc
)

target_include_directories(platutils_lib PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../>
)

target_link_libraries(platutils_lib PUBLIC
    log_lib
)

set_target_properties(platutils_lib PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
)
