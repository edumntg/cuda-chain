#pragma once

#include <boost/asio.hpp>
#include <boost/asio/ssl.hpp>
#include <string>
#include <unordered_set>
#include <memory>
#include "Peer.h"
#include <nlohmann/json.hpp>

class Peer;
class Node : public std::enable_shared_from_this<Node>{
public:
    Node(boost::asio::io_context& io_context, unsigned short port);
    void start();
    void connect_to_peer(const std::string& ip, unsigned short port);
    void handle_message(const std::shared_ptr<Peer>& sender, const std::string& message);

private:
    void accept_connection();
    void broadcast_new_peer(const std::shared_ptr<Peer>& new_peer);
    void broadcast_peer_disconnection(const std::shared_ptr<Peer>& disconnected_peer);
    void init_ssl_context();
    void request_known_peers(const std::shared_ptr<Peer>& peer);
    void send_known_peers(const std::shared_ptr<Peer>& requesting_peer);

    boost::asio::io_context& io_context_;
    boost::asio::ip::tcp::acceptor acceptor_;
    boost::asio::ssl::context ssl_context_;
    std::unordered_set<std::shared_ptr<Peer>> peers_;
    std::unordered_set<std::string> connected_peers_;  // To keep track of connected peers

};