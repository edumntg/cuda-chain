#include <iostream>
#include <boost/asio.hpp>
#include "p2p/Node.h"
#include <memory>
#include <thread>
#include <chrono>
#include "logger/Logger.h"

void send_periodic_messages(std::shared_ptr<Node> node) {
    while (true) {
        std::this_thread::sleep_for(std::chrono::seconds(3));
        node->send_messages_to_peers();
    }
}

int main(int argc, char* argv[]) {

    Logger logger_ = Logger("main");

    if (argc < 2 || argc > 4) {
         logger_.error() << "Usage: " << argv[0] << " <port> [peer_ip] [peer_port]" << std::endl;
        return 1;
    }

    unsigned short port = std::stoi(argv[1]);
    boost::asio::io_context io_context;
    
    // Create a shared_ptr to Node
    auto node = std::make_shared<Node>(io_context, port);

    logger_.info() << "Node started at port " << std::to_string(port) << std::endl;
    node->start();

    if (argc == 4) {
        std::string peer_ip = argv[2];
        unsigned short peer_port = std::stoi(argv[3]);
        logger_.info() << "Connecting to peer " << peer_ip << ":" << std::to_string(peer_port) << std::endl;
        node->connect_to_peer(peer_ip, peer_port);
    }

    // Start a new thread for sending periodic messages
    // std::thread message_thread(send_periodic_messages, node);

    io_context.run();

    // Join the message thread (this won't be reached in normal operation)
    // message_thread.join();

    return 0;
}