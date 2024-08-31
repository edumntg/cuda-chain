#include "Node.h"
#include <iostream>

Node::Node(boost::asio::io_context& io_context, unsigned short port)
    : io_context_(io_context),
      acceptor_(io_context, boost::asio::ip::tcp::endpoint(boost::asio::ip::tcp::v4(), port)),
      ssl_context_(boost::asio::ssl::context::sslv23) {
    init_ssl_context();
}

void Node::init_ssl_context() {
    ssl_context_.set_options(
        boost::asio::ssl::context::default_workarounds
        | boost::asio::ssl::context::no_sslv2
        | boost::asio::ssl::context::single_dh_use);

    // Load certificate and private key
    ssl_context_.use_certificate_chain_file("server.crt");
    ssl_context_.use_private_key_file("server.key", boost::asio::ssl::context::pem);

    // Optional: Load CA certificate for peer verification
    // ssl_context_.load_verify_file("ca.pem");
}

void Node::start() {
    accept_connection();
}

void Node::connect_to_peer(const std::string& ip, unsigned short port) {
    auto endpoint = boost::asio::ip::tcp::endpoint(
        boost::asio::ip::address::from_string(ip), port);

    auto socket = std::make_shared<boost::asio::ip::tcp::socket>(io_context_);

    socket->async_connect(endpoint, [this, socket, ip, port](const boost::system::error_code& ec) {
        if (!ec) {
            std::cout << "Connected to peer: " << ip << ":" << port << std::endl;

            auto peer = std::make_shared<Peer>(std::move(*socket), ssl_context_);
            peers_.insert(peer);
            peer->start();

            broadcast_new_peer(peer);
        } else {
            std::cerr << "Failed to connect to peer " << ip << ":" << port
                      << ". Error: " << ec.message() << std::endl;
        }
    });
}

void Node::accept_connection() {
    acceptor_.async_accept(
        [this](boost::system::error_code ec, boost::asio::ip::tcp::socket socket) {
            if (!ec) {
                std::cout << "New connection from: " << socket.remote_endpoint() << std::endl;
                auto peer = std::make_shared<Peer>(std::move(socket), ssl_context_);
                peers_.insert(peer);
                peer->start();
                broadcast_new_peer(peer);
            }
            accept_connection();
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
            } catch (const std::exception& e) {
                std::cerr << "Error broadcasting new peer to "
                          << peer->get_ip() << ":" << peer->get_port()
                          << ". Error: " << e.what() << std::endl;
            }
        }
    }

    std::cout << "Broadcasted new peer " << new_peer->get_ip() << ":"
              << new_peer->get_port() << " to " << peers_.size() - 1
              << " existing peers." << std::endl;
}

void Node::broadcast_peer_disconnection(const std::shared_ptr<Peer>& disconnected_peer) {
    // Implementation to broadcast peer disconnection to all connected peers
}