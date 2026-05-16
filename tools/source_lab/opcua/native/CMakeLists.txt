cmake_minimum_required(VERSION 3.16)

project(open62541_source_lab_native C)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

find_package(open62541 REQUIRED)

add_executable(open62541_source_simulator
    open62541_source_simulator.c
)

target_link_libraries(open62541_source_simulator
    PRIVATE
        open62541::open62541
)

add_executable(open62541_client_reader
    open62541_client_reader.c
)

target_link_libraries(open62541_client_reader
    PRIVATE
        open62541::open62541
)
