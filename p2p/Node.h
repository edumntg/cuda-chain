#pragma once

#include <boost/asio.hpp>
#include <boost/asio/ssl.hpp>
#include <string>
#include <unordered_set>
#include <memory>
#include "Peer.h"
#include <nlohmann/json.hpp>

class Node {
public:
    Node(boost::asio::io_context& io_context, unsigned short port);
    void start();
    void connect_to_peer(const std::string& ip, unsigned short port);

private:
    void accept_connection();
    void broadcast_new_peer(const std::shared_ptr<Peer>& new_peer);
    void broadcast_peer_disconnection(const std::shared_ptr<Peer>& disconnected_peer);
    void init_ssl_context();

    boost::asio::io_context& io_context_;
    boost::asio::ip::tcp::acceptor acceptor_;
    boost::asio::ssl::context ssl_context_;
    std::unordered_set<std::shared_ptr<Peer>> peers_;
};