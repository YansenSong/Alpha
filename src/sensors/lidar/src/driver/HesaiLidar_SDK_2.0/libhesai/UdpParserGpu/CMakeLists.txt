# UdpParserGpu module (CUDA)
# 依赖: udpParser_lib
# 条件: CUDA_FOUND

if(NOT CUDA_FOUND)
    message(STATUS "CUDA not found, skipping UdpParserGpu")
    return()
endif(NOT CUDA_FOUND)

add_library(udpParserGpu_lib STATIC
    udp_parser_gpu.cu
    src/general_parser_gpu.cu
    src/udp_p40_parser_gpu.cu
    src/udp_p64_parser_gpu.cu
    src/udp1_4_parser_gpu.cu
    src/udp1_8_parser_gpu.cu
    src/udp3_1_parser_gpu.cu
    src/udp3_2_parser_gpu.cu
    src/udp4_3_parser_gpu.cu
    src/udp4_7_parser_gpu.cu
    src/udp6_1_parser_gpu.cu
    src/udp7_2_parser_gpu.cu
    src/udp7_3_parser_gpu.cu
)

target_include_directories(udpParserGpu_lib PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/src>
)

target_link_libraries(udpParserGpu_lib PUBLIC
    udpParser_lib
    ${CUDA_LIBRARIES}
)

set_target_properties(udpParserGpu_lib PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
    CUDA_SEPARABLE_COMPILATION ON
)
