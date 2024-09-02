#include "Node.h"
#include <iostream>
#include <uuid/uuid.h>
#include <openssl/sha.h>
#include "../utils/utils.h"
#include "../matrix/Matrix.h"

Node::Node(boost::asio::io_context& io_context, unsigned short port)
    : io_context_(io_context),
      acceptor_(io_context, boost::asio::ip::tcp::endpoint(boost::asio::ip::tcp::v4(), port)),
      logger_("Node") {

    // Init logger
}

void Node::start() {
    accept_connection();
}

void Node::accept_connection() {
    acceptor_.async_accept(
        [this, self = shared_from_this()](boost::system::error_code ec, boost::asio::ip::tcp::socket socket) {
            if (!ec) {
                logger_.info() << "New connection from: " << socket.remote_endpoint().address().to_string() << ":" << std::to_string(socket.remote_endpoint().port()) << std::endl;
                // auto peer = std::make_shared<Peer>(std::move(socket), ssl_context_);
                auto peer = std::make_shared<Peer>(std::move(socket), socket.remote_endpoint().address().to_string(), socket.remote_endpoint().port());
                peer->set_node(self);
                peers_.insert(peer);
                peer->start();
                broadcast_new_peer(peer);
            }
            accept_connection();  // Continue accepting connections
        });
}

void Node::connect_to_peer(const std::string& ip, unsigned short port) {

    std::string peer_id = hash_str(ip + ":" + std::to_string(port));

    logger_.info() << "Peer with ip: " << ip << " and port: " << std::to_string(port) << " received ID: " << peer_id << std::endl;

    // Check if we're already connected to this peer
    if (connected_peers_.find(peer_id) != connected_peers_.end()) {
        logger_.warning() << "Already connected to peer: " << peer_id << std::endl;
        return;
    }

    auto endpoint = boost::asio::ip::tcp::endpoint(
        boost::asio::ip::address::from_string(ip), port);

    auto socket = std::make_shared<boost::asio::ip::tcp::socket>(io_context_);

    socket->async_connect(endpoint, [this, self = shared_from_this(), socket, ip, port, peer_id](const boost::system::error_code& ec) {
        if (!ec) {
            logger_.info() << "Successfully connected to peer: " << ip << ":" << std::to_string(port) << " (" << peer_id << ") " << std::endl << std::flush;

            auto peer = std::make_shared<Peer>(std::move(*socket), ip, port);
            peer->set_node(self);
            peers_.insert(peer);
            connected_peers_.insert(peer_id);
            peer->start();

            // Broadcast this new connection to all other peers
            broadcast_new_peer(peer);

            // Request the peer's known peers
            request_known_peers(peer);
        } else {
            logger_.error() << "Failed to connect to peer " << ip << ":" << std::to_string(port)
                      << ". Error: " << ec.message() << std::endl << std::flush;
        }
    });
}

void Node::broadcast_new_peer(const std::shared_ptr<Peer>& new_peer) {
    nlohmann::json peer_info = {
        {"type", "new_peer"},
        {"ip", new_peer->get_ip()},
        {"port", new_peer->get_port()}
    };

    std::string message = peer_info.dump();

    for (const auto& peer : peers_) {
        if (peer != new_peer) {
            try {
                peer->write_message(message);
                logger_.info() << "Broadcasted new peer " << new_peer->get_ip() << ":"
                  << std::to_string(new_peer->get_port()) << " to " << peer->get_ip() << ":"
                  << std::to_string(peer->get_port()) << std::endl;
            } catch (const std::exception& e) {
                logger_.error() << "Error broadcasting new peer to "
                          << peer->get_ip() << ":" << std::to_string(peer->get_port())
                          << ". Error: " << e.what() << std::endl;
            }
        }
    }
}

void Node::request_known_peers(const std::shared_ptr<Peer>& peer) {
    nlohmann::json request = {
        {"type", "request_known_peers"}
    };

    std::string message = request.dump();
    peer->write_message(message);
}

void Node::send_known_peers(const std::shared_ptr<Peer>& requesting_peer) {
    nlohmann::json known_peers = {
        {"type", "known_peers"},
        {"peers", nlohmann::json::array()}
    };

    for (const auto& peer : peers_) {
        if (peer != requesting_peer) {
            known_peers["peers"].push_back({
                {"ip", peer->get_ip()},
                {"port", peer->get_port()}
            });
        }
    }

    std::string message = known_peers.dump();
    requesting_peer->write_message(message);
}

// Add this method to handle incoming messages
void Node::handle_message(const std::shared_ptr<Peer>& sender, const std::string& message) {
    logger_.info() << "Received message from " << sender->get_ip() << ":" << std::to_string(sender->get_port())
              << ": " << message << std::endl << std::flush;
    try {
        auto json = nlohmann::json::parse(message);
        if (json["type"] == "new_peer") {
            const std::string ip = json["ip"];
            const unsigned short port = json["port"];
            connect_to_peer(ip, port);
        } else if (json["type"] == "request_known_peers") {
            send_known_peers(sender);
        } else if (json["type"] == "known_peers") {
            for (const auto& peer : json["peers"]) {
                connect_to_peer(peer["ip"], peer["port"]);
            }
        } else if (json["type"] == "periodic_message") {
            logger_.info() << "Received periodic message:" << std::endl
                      << "  From port: " << json["source_port"] << std::endl
                      << "  From connection:     " << sender->get_ip() << ":" << std::to_string(sender->get_port()) << std::endl << std::flush;
        } else if(json["type"] == "take_job_request") {
            // If we are free, accept the job
            if(compute_queue.size() < 100) {
                // Send message to peer accepting the request and requesting for the job data
                nlohmann::json json = {
                    {"type", "take_job_response"},
                    {"answer", "accepted"},
                    {"source_ip", acceptor_.local_endpoint().address().to_string()},
                    {"source_port", acceptor_.local_endpoint().port()},
                    {"target_ip", sender->get_ip()},
                    {"target_port", sender->get_port()}
                };

                // send
                send_direct_message(sender, json);
                logger_.info() << "Accepted job request from " << sender->get_ip() << ":" << std::to_string(sender->get_port()) << std::endl;
            }
        } else if(json["type"] == "take_job_response") {
            if(json["answer"] == "accepted") {
                logger_.info() << "Peer with ID: " << sender->get_ip() << ":" << std::to_string(sender->get_port()) << " accepted the job" << std::endl;
                // Peer accepted the job, so send the data

                // Send job data
                nlohmann::json job = pop_job();

                nlohmann::json json_data = {
                    {"type", "job_data"},
                    {"id", generate_job_id(job)},
                    {"job", job}
                };

                send_direct_message(sender, json_data);
                logger_.info() << "Send job data to " << sender->get_ip() << ":" << std::to_string(sender->get_port()) << " with id: " << json["id"] << std::endl;
            }
        } else if(json["type"] == "job_data") {
            // We received job data so perform matrix multiplication
            // Get job data
            nlohmann::json job = json["job"];
            std::string id = json["id"];
            logger_.info() << "Executing job with id: " << id << std::endl;

            Matrix A = Matrix::from_json(job["a_rows"]);
            Matrix B = Matrix::from_json(job["b_rows"]);

            // Perform multiplication
            Matrix C = A.multiply(B);

            // Perform matrix multiplication
            // multiply_rows(job["a_rows"], job["b_rows"], result);
        } else {
            logger_.info() << "Received unknown message type: " << json["type"] << std::endl << std::flush;
        }
    } catch (const std::exception& e) {
        std::cerr << "Error parsing message: " << e.what() << std::endl << std::flush;
    }
}

void Node::broadcast_peer_disconnection(const std::shared_ptr<Peer>& disconnected_peer) {
    // Create a JSON object with the disconnected peer's information
    nlohmann::json peer_info = {
        {"type", "peer_disconnected"},
        {"ip", disconnected_peer->get_ip()},
        {"port", disconnected_peer->get_port()}
    };

    std::string message = peer_info.dump();

    // Remove the disconnected peer from our set of peers
    peers_.erase(disconnected_peer);

    // Broadcast the disconnection to all remaining peers
    for (const auto& peer : peers_) {
        try {
            peer->write_message(message);
        } catch (const std::exception& e) {
            std::cerr << "Error broadcasting peer disconnection to "
                      << peer->get_ip() << ":" << peer->get_port()
                      << ". Error: " << e.what() << std::endl;
            // Consider handling this peer's potential disconnection as well
        }
    }

    logger_.info() << "Broadcasted disconnection of peer " << disconnected_peer->get_ip() << ":"
              << std::to_string(disconnected_peer->get_port()) << " to " << std::to_string(peers_.size())
              << " remaining peers." << std::endl;
}

// Add this function to Node.cpp
void Node::send_messages_to_peers() {
    logger_.info() << "Attempting to send messages to " << std::to_string(peers_.size()) << " peers." << std::endl << std::flush;
    for (const auto& peer : peers_) {
        nlohmann::json message = {
            {"type", "periodic_message"},
            {"source_ip", acceptor_.local_endpoint().address().to_string()},
            {"source_port", acceptor_.local_endpoint().port()},
            {"target_ip", peer->get_ip()},
            {"target_port", peer->get_port()}
        };

        std::string message_str = message.dump();
        try {
            peer->write_message(message_str);
            logger_.info() << "Sent message to " << peer->get_ip() << ":" << std::to_string(peer->get_port())
                      << " from " << acceptor_.local_endpoint().address().to_string() 
                      << ":" << std::to_string(acceptor_.local_endpoint().port()) << std::endl << std::flush;
        } catch (const std::exception& e) {
            logger_.error() << "Error sending message to " << peer->get_ip() << ":" << std::to_string(peer->get_port())
                      << ". Error: " << e.what() << std::endl << std::flush;
        }
    }
}

void Node::send_matrix_to_peers(double **A, double **B, double **C) {
    // Get num of rows and columns
    int rows_A = sizeof(A);
    int cols_A = sizeof(A[0]);
    int rows_B = sizeof(B);
    int cols_B = sizeof(B[0]);

    // First, calculate the number of rows to be computed by self, and then by peers
    int rows_per_peer = rows_A / (peers_.size() + 1);

    // Add rows to queue
    for(int i = 0; i < peers_.size(); i++) {
        int start_row = i * rows_per_peer;
        int end_row = (i + 1) * rows_per_peer;

        double** a_rows = new double*[rows_per_peer];
        double** b_rows = new double*[rows_B];

        for(int j = start_row; j < end_row; j++) {
            a_rows[j - start_row] = A[j];
        }

        for(int j = 0; j < rows_B; j++) {
            b_rows[j] = B[j];
        }

        queue_rows("job_" + std::to_string(i), new int[2] {rows_per_peer, cols_A}, new int[2] {rows_B, cols_B}, a_rows, b_rows);
    }

    // After all jobs have been queued, send a message to all peers so they take the jobs
    ask_peers_to_take_jobs();

}

void Node::wait() {

}

void Node::queue_rows(std::string id,
                 int a_size[2], int b_size[2],
                 double** a_rows, double** b_rows) {
    nlohmann::json json_obj;
    json_obj["id"] = id;
    json_obj["a_size"][0] = a_size[0];
    json_obj["a_size"][1] = a_size[1];
    json_obj["b_size"][0] = b_size[0];
    json_obj["b_size"][1] = b_size[1];

    // Convert 2D arrays to JSON arrays
    for (int i = 0; i < a_size[0]; ++i) {
        for (int j = 0; j < a_size[1]; ++j) {
            json_obj["a_rows"][i][j] = a_rows[i][j];
        }
    }

    for (int i = 0; i < b_size[0]; ++i) {
        for (int j = 0; j < b_size[1]; ++j) {
            json_obj["b_rows"][i][j] = b_rows[i][j];
        }
    }

    jobs_queue.push(json_obj);
    logger_.info() << "Queued job with ID: " << id << std::endl;
}

nlohmann::json Node::pop_job() {

    if(jobs_queue.empty()) {
        return nlohmann::json("{}");
    }

    nlohmann::json json_obj = jobs_queue.front();
    jobs_queue.pop();

    return json_obj;
}

void Node::ask_peers_to_take_jobs() {
    logger_.info() << "Asking peers to take queued jobs" << std::endl << std::flush;
    for (const auto& peer : peers_) {
        nlohmann::json message = {
            {"type", "take_job_request"},
            {"source_ip", acceptor_.local_endpoint().address().to_string()},
            {"source_port", acceptor_.local_endpoint().port()},
            {"target_ip", peer->get_ip()},
            {"target_port", peer->get_port()}
        };

        std::string message_str = message.dump();
        try {
            peer->write_message(message_str);
            logger_.info() << "Sent message to " << peer->get_ip() << ":" << std::to_string(peer->get_port())
                      << " from " << acceptor_.local_endpoint().address().to_string()
                      << ":" << std::to_string(acceptor_.local_endpoint().port()) << std::endl << std::flush;
        } catch (const std::exception& e) {
            logger_.error() << "Error sending message to " << peer->get_ip() << ":" << std::to_string(peer->get_port())
                      << ". Error: " << e.what() << std::endl << std::flush;
        }
    }
}

void Node::send_direct_message(const std::shared_ptr<Peer> &sender, const nlohmann::json& json) {
    sender->write_message(json.dump());
}

std::string Node::generate_job_id(nlohmann::json json) {
    return hash_str(json.dump());
}

