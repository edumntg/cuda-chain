#pragma once

#include <boost/asio.hpp>
#include <boost/asio/ssl.hpp>
#include <string>
#include <unordered_set>
#include <memory>
#include "Peer.h"
#include <nlohmann/json.hpp>
#include "../logger/Logger.h"
#include <queue>

class Peer;
class Node : public std::enable_shared_from_this<Node>{
public:
    Node(boost::asio::io_context& io_context, unsigned short port);
    void start();
    void connect_to_peer(const std::string& ip, unsigned short port);
    void handle_message(const std::shared_ptr<Peer>& sender, const std::string& message);
    void send_messages_to_peers();
    void send_matrix_to_peers(double** A, double** B, double** C);
    void wait();
    void queue_rows(std::string id,
                 int a_size[2], int b_size[2],
                 double** a_rows, double** b_rows);

    nlohmann::json Node::pop_job();
    void send_job_to_peers();
    void ask_peers_to_take_jobs();

private:
    void accept_connection();
    void broadcast_new_peer(const std::shared_ptr<Peer>& new_peer);
    void broadcast_peer_disconnection(const std::shared_ptr<Peer>& disconnected_peer);
    void request_known_peers(const std::shared_ptr<Peer>& peer);
    void send_known_peers(const std::shared_ptr<Peer>& requesting_peer);

    boost::asio::io_context& io_context_;
    boost::asio::ip::tcp::acceptor acceptor_;
    std::unordered_set<std::shared_ptr<Peer>> peers_;
    std::unordered_set<std::string> connected_peers_;  // To keep track of connected peers
    Logger logger_;
    std::queue<nlohmann::json> jobs_queue;


};