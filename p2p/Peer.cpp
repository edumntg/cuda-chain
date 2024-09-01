#include "Peer.h"
#include <iostream>
#include <boost/asio/write.hpp>
#include <boost/asio/read.hpp>
#include <boost/endian/conversion.hpp>
#include <utility>

Peer::Peer(boost::asio::ip::tcp::socket socket, std::string ip, const unsigned short port) // Remove ssl_context parameter
    : socket_(std::move(socket)), // Change ssl_socket_ to socket_
      read_buffer_(1024), message_length_(0),
    ip_(std::move(ip)),
    port_(port),
    logger_("Peer")
    {
    // No SSL context
}

void Peer::start() {
    read_message();
}

void Peer::disconnect() {
    boost::system::error_code ec;
    socket_.close(ec); // Change ssl_socket_ to socket_
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
    boost::asio::async_read(socket_, // Change ssl_socket_ to socket_
        boost::asio::buffer(&message_length_, sizeof(uint32_t)),
        [this, self](boost::system::error_code ec, std::size_t /*length*/)
        {
            if (!ec) {
                message_length_ = boost::endian::big_to_native(message_length_);
                read_buffer_.resize(message_length_);
                boost::asio::async_read(socket_, // Change ssl_socket_ to socket_
                    boost::asio::buffer(read_buffer_),
                    [this, self](boost::system::error_code ec, std::size_t /*length*/)
                    {
                        if (!ec) {
                            std::string message(read_buffer_.begin(), read_buffer_.end());
                            handle_message(message);
                        } else {
                            std::cerr << "Error reading message body: " << ec.message() << std::endl;
                        }
                        read_message();
                    });
            } else {
                if (ec == boost::asio::error::eof ||
                    ec == boost::asio::error::connection_reset) {
                    handle_error(ec);
                } else {
                    read_message();
                }
            }
        });
}

void Peer::write_message(const std::string& message) {
    auto self(shared_from_this());
    uint32_t length = boost::endian::native_to_big(static_cast<uint32_t>(message.size()));
    std::vector<boost::asio::const_buffer> buffers;
    buffers.emplace_back(boost::asio::buffer(&length, sizeof(uint32_t)));
    buffers.push_back(boost::asio::buffer(message));

    boost::asio::async_write(socket_, buffers, // Change ssl_socket_ to socket_
        [this, self, message](const boost::system::error_code &ec, std::size_t /*length*/)
        {
            if (ec) {
                logger_.error() << "Error writing message to " << get_ip() << ":" << std::to_string(get_port())
                          << ". Error: " << ec.message() << std::endl;
                handle_error(ec);
            }
        });
}

void Peer::set_node(const std::weak_ptr<Node> &node) {
    node_ = node;
}

void Peer::handle_message(const std::string& message) {
    logger_.info() << "Received message from " << get_ip() << ":" << std::to_string(get_port()) << ": " << message << std::endl;

    if (const auto node = node_.lock()) {
        node->handle_message(shared_from_this(), message);
    }
}

void Peer::handle_error(const boost::system::error_code& error) {
    logger_.error() << "Error in communication with " << get_ip() << ":" << std::to_string(get_port())
              << ". Error: " << error.message() << std::endl;
    disconnect();
}