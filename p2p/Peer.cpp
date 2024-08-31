#include "Peer.h"
#include <iostream>
#include <boost/asio/write.hpp>
#include <boost/asio/read.hpp>
#include <boost/endian/conversion.hpp>

Peer::Peer(boost::asio::ip::tcp::socket socket, boost::asio::ssl::context& ssl_context)
    : ssl_socket_(std::move(socket), ssl_context),
      read_buffer_(1024) {
    ip_ = ssl_socket_.lowest_layer().remote_endpoint().address().to_string();
    port_ = ssl_socket_.lowest_layer().remote_endpoint().port();
}

void Peer::start() {
    do_handshake();
}

void Peer::do_handshake() {
    auto self(shared_from_this());
    ssl_socket_.async_handshake(boost::asio::ssl::stream_base::server,
        [this, self](const boost::system::error_code& error) {
            if (!error) {
                read_message();
            } else {
                handle_error(error);
            }
        });
}

void Peer::disconnect() {
    boost::system::error_code ec;
    ssl_socket_.lowest_layer().close(ec);
    if (ec) {
        std::cerr << "Error closing socket: " << ec.message() << std::endl;
    }
}

std::string Peer::get_ip() const {
    return ip_;
}

unsigned short Peer::get_port() const {
    return port_;
}

void Peer::read_message() {
    auto self(shared_from_this());
    boost::asio::async_read(ssl_socket_,
        boost::asio::buffer(&message_length_, sizeof(uint32_t)),
        [this, self](boost::system::error_code ec, std::size_t /*length*/)
        {
            if (!ec) {
                message_length_ = boost::endian::big_to_native(message_length_);
                read_buffer_.resize(message_length_);
                boost::asio::async_read(ssl_socket_,
                    boost::asio::buffer(read_buffer_),
                    [this, self](boost::system::error_code ec, std::size_t /*length*/)
                    {
                        if (!ec) {
                            std::string message(read_buffer_.begin(), read_buffer_.end());
                            handle_message(message);
                            read_message();  // Continue reading
                        } else {
                            handle_error(ec);
                        }
                    });
            } else {
                handle_error(ec);
            }
        });
}

void Peer::write_message(const std::string& message) {
    auto self(shared_from_this());
    uint32_t length = boost::endian::native_to_big(static_cast<uint32_t>(message.size()));
    std::vector<boost::asio::const_buffer> buffers;
    buffers.push_back(boost::asio::buffer(&length, sizeof(uint32_t)));
    buffers.push_back(boost::asio::buffer(message));

    boost::asio::async_write(ssl_socket_, buffers,
        [this, self](boost::system::error_code ec, std::size_t /*length*/)
        {
            if (ec) {
                handle_error(ec);
            }
        });
}

void Peer::set_node(std::weak_ptr<Node> node) {
    node_ = node;
}

void Peer::handle_message(const std::string& message) {
    std::cout << "Received message from " << get_ip() << ":" << get_port() << ": " << message << std::endl;

    try {
        auto json = nlohmann::json::parse(message);
        if (json["type"] == "new_peer") {
            std::string ip = json["ip"];
            unsigned short port = json["port"];

            // Notify the Node to connect to the new peer
            if (auto node = node_.lock()) {
                node->connect_to_peer(ip, port);
            }
        } else if (json["type"] == "peer_disconnected") {
            // Handle peer disconnection if needed
        }
    } catch (const std::exception& e) {
        std::cerr << "Error parsing message: " << e.what() << std::endl;
    }
}

void Peer::handle_error(const boost::system::error_code& error) {
    std::cerr << "Error in communication with " << get_ip() << ":" << get_port()
              << ". Error: " << error.message() << std::endl;
    disconnect();
}