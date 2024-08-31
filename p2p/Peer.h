#pragma once

#include <boost/asio.hpp>
#include <openssl/ssl.h>
#include <string>
#include <functional>

class Peer {
public:
    Peer(boost::asio::ip::tcp::socket socket);
    void start();
    void disconnect();
    std::string get_ip() const;
    unsigned short get_port() const;

    // Add equality operator
    bool operator==(const Peer& other) const {
        return ip_ == other.ip_ && port_ == other.port_;
    }

private:
    void read_message();
    void write_message(const std::string& message);

    boost::asio::ip::tcp::socket socket_;
    SSL* ssl_;
    std::string ip_;
    unsigned short port_;
};

// Add hash function for Peer
namespace std {
    template <>
    struct hash<Peer> {
        std::size_t operator()(const Peer& p) const {
            return std::hash<std::string>()(p.get_ip()) ^ std::hash<unsigned short>()(p.get_port());
        }
    };
}