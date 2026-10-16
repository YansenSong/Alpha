# Logger module
# 无外部依赖，是最底层的模块

if(BUILD_LOG_LIB_SHARED)
    add_library(log_lib SHARED
        src/logger.cc
    )
    target_compile_definitions(log_lib PRIVATE 
        LOG_LIB_API_EXPORTS=1 
        BUILD_LOG_LIB_SHARED=1
    )
else(BUILD_LOG_LIB_SHARED)
    add_library(log_lib STATIC
        src/logger.cc
    )
endif(BUILD_LOG_LIB_SHARED)

target_include_directories(log_lib PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
)

target_link_libraries(log_lib PUBLIC
    Threads::Threads
)

set_target_properties(log_lib PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
)
