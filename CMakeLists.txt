cmake_minimum_required(VERSION 3.10)
project(P2PNetwork)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find required packages
find_package(Boost REQUIRED COMPONENTS system)
find_package(OpenSSL REQUIRED)

# For nlohmann/json, we'll use the single header file approach
# Download the single header file if it doesn't exist
if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/json.hpp")
    file(DOWNLOAD
            "https://github.com/nlohmann/json/releases/download/v3.11.2/json.hpp"
            "${CMAKE_CURRENT_SOURCE_DIR}/json.hpp"
            SHOW_PROGRESS
    )
endif()

# Add your source files
set(SOURCES
        main.cpp
        p2p/Node.cpp
        p2p/Peer.cpp
)

# Create the executable
add_executable(p2p_node ${SOURCES})

# Include directories
target_include_directories(p2p_node PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

# Link libraries
target_link_libraries(p2p_node PRIVATE
        Boost::system
        OpenSSL::SSL
        OpenSSL::Crypto
        pthread
)

# If you're on a Unix-like system and want to link against the math library
if(UNIX)
    target_link_libraries(p2p_node PRIVATE m)
endif()