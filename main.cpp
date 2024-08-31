#include <iostream>
#include <boost/asio.hpp>
#include "p2p/Node.h"
#include <memory>

int main(int argc, char* argv[]) {
    if (argc < 2 || argc > 4) {
        std::cerr << "Usage: " << argv[0] << " <port> [peer_ip] [peer_port]" << std::endl;
        return 1;
    }

    unsigned short port = std::stoi(argv[1]);
    boost::asio::io_context io_context;
    
    // Create a shared_ptr to Node
    auto node = std::make_shared<Node>(io_context, port);

    if (argc == 4) {
        std::string peer_ip = argv[2];
        unsigned short peer_port = std::stoi(argv[3]);
        node->connect_to_peer(peer_ip, peer_port);
    }

    std::cout << "Node started at port " << port << std::endl;
    node->start();
    io_context.run();

    return 0;
}