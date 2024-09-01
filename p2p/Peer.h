#pragma once

#include <boost/asio.hpp>
#include <boost/asio/ssl.hpp>
#include <string>
#include <vector>
#include <memory>
#include <nlohmann/json.hpp>
#include "../logger/Logger.h"
#include "Node.h"

class Node;
class Peer : public std::enable_shared_from_this<Peer> {
public:
    // Peer(boost::asio::ip::tcp::socket socket, boost::asio::ssl::context& ssl_context);
    Peer(boost::asio::ip::tcp::socket socket, std::string ip, unsigned short port);
    void start();
    void disconnect();
    std::string get_ip() const;
    unsigned short get_port() const;
    void write_message(const std::string& message);
    void set_node(const std::weak_ptr<Node> &node);  // Add this method

    // Add equality operator
    bool operator==(const Peer& other) const {
        return ip_ == other.ip_ && port_ == other.port_;
    }

private:
    void do_handshake();
    void read_message();
    void handle_message(const std::string& message);
    void handle_error(const boost::system::error_code& error);

    // boost::asio::ssl::stream<boost::asio::ip::tcp::socket> ssl_socket_;
    std::string ip_;
    unsigned short port_;
    std::vector<char> read_buffer_;
    uint32_t message_length_;
    std::weak_ptr<Node> node_;  // Add this member variable
    boost::asio::ip::tcp::socket socket_;
    Logger logger_;
};

// Add hash function for Peer
namespace std {
    template <>
    struct hash<Peer> {
        std::size_t operator()(const Peer& p) const noexcept {
            return std::hash<std::string>()(p.get_ip()) ^ std::hash<unsigned short>()(p.get_port());
        }
    };
}