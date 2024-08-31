#include "Peer.h"
#include <iostream>

Peer::Peer(boost::asio::ip::tcp::socket socket)
    : socket_(std::move(socket)) {
    ip_ = socket_.remote_endpoint().address().to_string();
    port_ = socket_.remote_endpoint().port();
}

void Peer::start() {
    read_message();
}

void Peer::disconnect() {
    socket_.close();
}

std::string Peer::get_ip() const {
    return ip_;
}

unsigned short Peer::get_port() const {
    return port_;
}

void Peer::read_message() {
    // Implementation to read messages from the peer
}

void Peer::write_message(const std::string& message) {
    // Implementation to write messages to the peer
}