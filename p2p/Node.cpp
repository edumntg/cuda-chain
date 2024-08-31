#include "Node.h"
#include <iostream>

Node::Node(boost::asio::io_context& io_context, unsigned short port)
    : io_context_(io_context),
      acceptor_(io_context, boost::asio::ip::tcp::endpoint(boost::asio::ip::tcp::v4(), port)),
      ssl_context_(boost::asio::ssl::context::sslv23) {
    init_ssl_context();
}

void Node::init_ssl_context() {
    try {
        ssl_context_.set_options(
            boost::asio::ssl::context::default_workarounds
            | boost::asio::ssl::context::no_sslv2
            | boost::asio::ssl::context::single_dh_use);

        // Load certificate and private key
        ssl_context_.use_certificate_chain_file("server.crt");
        ssl_context_.use_private_key_file("server.key", boost::asio::ssl::context::pem);

        // Optional: Load CA certificate for peer verification
        // ssl_context_.load_verify_file("ca.pem");
    } catch (const boost::system::system_error& e) {
        std::cerr << "SSL context initialization failed: " << e.what() << std::endl;
        std::cerr << "Make sure 'server.crt' and 'server.key' files are present in the current directory." << std::endl;
        throw; // Re-throw the exception to stop the program
    }
}

void Node::start() {
    accept_connection();
}

void Node::accept_connection() {
    acceptor_.async_accept(
        [this, self = shared_from_this()](boost::system::error_code ec, boost::asio::ip::tcp::socket socket) {
            if (!ec) {
                std::cout << "New connection from: " << socket.remote_endpoint() << std::endl;
                auto peer = std::make_shared<Peer>(std::move(socket), ssl_context_);
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

    // Check if we're already connected to this peer
    if (connected_peers_.find(peer_id) != connected_peers_.end()) {
        std::cout << "Already connected to peer: " << peer_id << std::endl;
        return;
    }

    auto endpoint = boost::asio::ip::tcp::endpoint(
        boost::asio::ip::address::from_string(ip), port);

    auto socket = std::make_shared<boost::asio::ip::tcp::socket>(io_context_);

    socket->async_connect(endpoint, [this, self = shared_from_this(), socket, ip, port, peer_id](const boost::system::error_code& ec) {
        if (!ec) {
            std::cout << "Connected to peer: " << ip << ":" << port << std::endl;

            auto peer = std::make_shared<Peer>(std::move(*socket), ssl_context_);
            peer->set_node(self);
            peers_.insert(peer);
            connected_peers_.insert(peer_id);
            peer->start();

            // Don't broadcast new peer here, as we're connecting to an existing peer
        } else {
            std::cerr << "Failed to connect to peer " << ip << ":" << port
                      << ". Error: " << ec.message() << std::endl;
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
                  << new_peer->get_port() << " to " << peers_.size() - 1
                  << " existing peers." << std::endl;
            } catch (const std::exception& e) {
                std::cerr << "Error broadcasting new peer to "
                          << peer->get_ip() << ":" << peer->get_port()
                          << ". Error: " << e.what() << std::endl;
            }
        }
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