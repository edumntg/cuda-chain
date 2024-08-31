#pragma once

#include <boost/asio.hpp>
#include <openssl/ssl.h>
#include <string>
#include <unordered_set>
#include <memory>
#include <nlohmann/json.hpp>
#include "Peer.h"

class Node {
public:
    Node(boost::asio::io_context& io_context, unsigned short port);
    void start();
    void connect_to_peer(const std::string& ip, unsigned short port);

private:
    void accept_connection();
    void handle_new_connection(const boost::system::error_code& error);
    void broadcast_new_peer(const std::shared_ptr<Peer>& new_peer);
    void broadcast_peer_disconnection(const std::shared_ptr<Peer>& disconnected_peer);

    boost::asio::io_context& io_context_;
    boost::asio::ip::tcp::acceptor acceptor_;
    std::unordered_set<std::shared_ptr<Peer>> peers_;
};