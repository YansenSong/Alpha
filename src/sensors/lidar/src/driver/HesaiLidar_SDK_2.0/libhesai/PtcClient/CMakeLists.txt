# PtcClient module (包含 PtcParser)
# 依赖: platutils_lib
# 可选依赖: OpenSSL (当 WITH_PTCS_USE=ON)

set(PTC_SOURCES
    src/ptc_client.cc
    src/tcp_client.cc
    ${CMAKE_CURRENT_SOURCE_DIR}/../PtcParser/src/general_ptc_parser.cc
    ${CMAKE_CURRENT_SOURCE_DIR}/../PtcParser/src/ptc_1_0_parser.cc
    ${CMAKE_CURRENT_SOURCE_DIR}/../PtcParser/src/ptc_2_0_parser.cc
    ${CMAKE_CURRENT_SOURCE_DIR}/../PtcParser/ptc_parser.cc
)

# SSL 支持
if(WITH_PTCS_USE)
    list(APPEND PTC_SOURCES src/tcp_ssl_client.cc)
endif(WITH_PTCS_USE)

add_library(ptcClient_lib STATIC ${PTC_SOURCES})

target_include_directories(ptcClient_lib PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../PtcParser/include>
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/../PtcParser>
)

target_link_libraries(ptcClient_lib PUBLIC
    platutils_lib
)

# OpenSSL 支持
if(WITH_PTCS_USE)
    find_package(OpenSSL REQUIRED)
    target_link_libraries(ptcClient_lib PUBLIC
        OpenSSL::SSL
        OpenSSL::Crypto
    )
    target_include_directories(ptcClient_lib PUBLIC
        ${OPENSSL_INCLUDE_DIR}
    )
    target_compile_definitions(ptcClient_lib PUBLIC WITH_PTCS_USE=1)
endif(WITH_PTCS_USE)

# 条件编译定义

set_target_properties(ptcClient_lib PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
)
