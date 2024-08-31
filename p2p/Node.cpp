#include "Node.h"
#include <iostream>

Node::Node(boost::asio::io_context& io_context, unsigned short port)
    : io_context_(io_context),
      acceptor_(io_context, boost::asio::ip::tcp::endpoint(boost::asio::ip::tcp::v4(), port)),
      // ssl_context_(boost::asio::ssl::context::sslv23),
      listening_port_(port) {
    // init_ssl_context();
}

// void Node::init_ssl_context() {
//     try {
//         ssl_context_.set_options(
//             boost::asio::ssl::context::default_workarounds
//             | boost::asio::ssl::context::no_sslv2
//             | boost::asio::ssl::context::single_dh_use);
//
//         // Load certificate and private key
//         ssl_context_.use_certificate_chain_file("server.crt");
//         ssl_context_.use_private_key_file("server.key", boost::asio::ssl::context::pem);
//
//         // Optional: Load CA certificate for peer verification
//         // ssl_context_.load_verify_file("ca.pem");
//     } catch (const boost::system::system_error& e) {
//         std::cerr << "SSL context initialization failed: " << e.what() << std::endl;
//         std::cerr << "Make sure 'server.crt' and 'server.key' files are present in the current directory." << std::endl;
//         throw; // Re-throw the exception to stop the program
//     }
// }

void Node::start() {
    accept_connection();
}

void Node::accept_connection() {
    acceptor_.async_accept(
        [this, self = shared_from_this()](boost::system::error_code ec, boost::asio::ip::tcp::socket socket) {
            if (!ec) {
                std::cout << "New connection from: " << socket.remote_endpoint() << std::endl;
                // auto peer = std::make_shared<Peer>(std::move(socket), ssl_context_);
                auto peer = std::make_shared<Peer>(std::move(socket));
                peer->set_node(self);
                peers_.insert(peer);
                peer->start();
                broadcast_new_peer(peer);
            }
            accept_connection();  // Continue accepting connections
        });
}

void Node::connect_to_peer(const std::string& ip, unsigned short port) {
    std::string peer_id = ip + ":" + std::to_string(port);
    std::cout << "Peer with ip: " << ip << " and port: " << port << " received ID: " << peer_id << std::endl;

    // Check if we're already connected to this peer
    if (connected_peers_.find(peer_id) != connected_peers_.end()) {
        std::cout << "Already connected to peer: " << peer_id << std::endl;
        return;
    }

    auto endpoint = boost::asio::ip::tcp::endpoint(
        boost::asio::ip::address::from_string("127.0.0.1"), port);

    auto socket = std::make_shared<boost::asio::ip::tcp::socket>(io_context_);

    socket->async_connect(endpoint, [this, self = shared_from_this(), socket, ip, port, peer_id](const boost::system::error_code& ec) {
        if (!ec) {
            std::cout << "Successfully connected to peer: " << ip << ":" << port << std::endl << std::flush;
            std::cout << "Connected to peer: " << ip << ":" << port << std::endl;

            // auto peer = std::make_shared<Peer>(std::move(*socket), ssl_context_);
            auto peer = std::make_shared<Peer>(std::move(*socket));
            peer->set_node(self);
            peers_.insert(peer);
            connected_peers_.insert(peer_id);
            peer->start();

            // Broadcast this new connection to all other peers
            broadcast_new_peer(peer);

            // Request the peer's known peers
            request_known_peers(peer);
        } else {
            std::cerr << "Failed to connect to peer " << ip << ":" << port
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
                std::cout << "Broadcasted new peer " << new_peer->get_ip() << ":"
                  << new_peer->get_port() << " to " << peer->get_ip() << ":"
                  << peer->get_port() << std::endl;
            } catch (const std::exception& e) {
                std::cerr << "Error broadcasting new peer to "
                          << peer->get_ip() << ":" << peer->get_port()
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
    std::cout << "Received message at listening port " << listening_port_ << " from " << sender->get_ip() << ":" << sender->get_port()
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
            std::cout << "Received periodic message:" << std::endl
                      << "  From listening port: " << json["source_port"] << std::endl
                      << "  From connection:     " << sender->get_ip() << ":" << sender->get_port() << std::endl
                      << "  To listening port:   " << listening_port_ << std::endl << std::flush;
        } else {
            std::cout << "Received unknown message type: " << json["type"] << std::endl << std::flush;
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

    std::cout << "Broadcasted disconnection of peer " << disconnected_peer->get_ip() << ":"
              << disconnected_peer->get_port() << " to " << peers_.size()
              << " remaining peers." << std::endl;
}

// Add this function to Node.cpp
void Node::send_messages_to_peers() {
    std::cout << "Attempting to send messages to " << peers_.size() << " peers from listening port " << listening_port_ << "." << std::endl << std::flush;
    for (const auto& peer : peers_) {
        nlohmann::json message = {
            {"type", "periodic_message"},
            {"source_ip", acceptor_.local_endpoint().address().to_string()},
            {"source_port", listening_port_},
            {"target_ip", peer->get_ip()},
            {"target_port", peer->get_port()}
        };

        std::string message_str = message.dump();
        try {
            peer->write_message(message_str);
            std::cout << "Sent message from listening port " << listening_port_ << " to " << peer->get_ip() << ":" << peer->get_port()
                      << " from " << acceptor_.local_endpoint().address().to_string() 
                      << ":" << acceptor_.local_endpoint().port() << std::endl << std::flush;
        } catch (const std::exception& e) {
            std::cerr << "Error sending message to " << peer->get_ip() << ":" << peer->get_port() 
                      << ". Error: " << e.what() << std::endl << std::flush;
        }
    }
}