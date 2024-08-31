#!/bin/bash

if [ "$#" -lt 1 ] || [ "$#" -gt 3 ]; then
    echo "Usage: $0 <port> [peer_ip] [peer_port]"
    exit 1
fi

./build/p2p_node "$@"