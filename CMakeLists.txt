cmake_minimum_required(VERSION 3.10)
project(P2PNetwork)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Boost REQUIRED COMPONENTS system)
find_package(OpenSSL REQUIRED)

include_directories(${Boost_INCLUDE_DIRS} ${OPENSSL_INCLUDE_DIR})

add_executable(p2p_node
        main.cpp
        p2p/Node.cpp
        p2p/Peer.cpp
)

target_link_libraries(p2p_node
        ${Boost_LIBRARIES}
        ${OPENSSL_LIBRARIES}
        pthread
)