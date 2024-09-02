#include <iostream>
#include <boost/asio.hpp>
#include "p2p/Node.h"
#include <memory>
#include <thread>
#include <chrono>
#include "logger/Logger.h"
#include <random>
#include <ctime>

double** initialize_random_matrix(int rows, int columns) {
    auto** matrix = new double*[rows];
    for (int i = 0; i < rows * columns; i++) {
        matrix[i] = new double[columns];
    }

    // Initialize random number generator
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_real_distribution<double> dis(0.0, 1.0);

    // Initialize matrix with random values
    for (int i = 0; i < rows; ++i) {
        for (int j = 0; j < columns; ++j) {
            matrix[i][j] = dis(gen);
        }
    }

    return matrix;
}

void deallocate_matrix(double** matrix) {
    int rows = sizeof(matrix);
    for (int i = 0; i < rows; i++) {
        delete[] matrix[i];
    }
    delete[] matrix;
}

void send_periodic_messages(Logger logger, std::shared_ptr<Node> node, bool run) {
    // We perform a matrix multiplication each 3 seconds
    if(!run) {
        return;
    }
    while (true) {
        std::this_thread::sleep_for(std::chrono::seconds(10));

        if(!node->get_peers().empty()) {
            // Initialize matrices A and B

            // Initialize matrix A (100x100)
            double** A = initialize_random_matrix(100, 100);

            // Initialize matrix B (100x50)
            double** B = initialize_random_matrix(100, 50);

            // Create result matrix (100x50)
            auto** C = new double*[sizeof(A)];
            for (int i = 0; i < sizeof(A); i++) {
                C[i] = new double[sizeof(A[0])];
            }

            // Send matrices to peers and wait for results
            node->send_matrix_to_peers(A, B, C);

            node->wait();

            logger.info() << "Matrix multiplication completed" << std::endl;

            deallocate_matrix(A);
            deallocate_matrix(B);
            deallocate_matrix(C);


            // node->send_messages_to_peers();
        }
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

    bool run = true;
    if (argc == 4) {
        run = false;
        std::string peer_ip = argv[2];
        unsigned short peer_port = std::stoi(argv[3]);
        logger_.info() << "Connecting to peer " << peer_ip << ":" << std::to_string(peer_port) << std::endl;
        node->connect_to_peer(peer_ip, peer_port);
    }

    // Start a new thread for sending periodic messages
    std::thread message_thread(send_periodic_messages, logger_, node, run);

    io_context.run();

    // Join the message thread (this won't be reached in normal operation)
    message_thread.join();

    return 0;
}