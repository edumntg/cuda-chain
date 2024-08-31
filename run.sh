#!/bin/bash

# Check if OpenSSL is installed
if ! command -v openssl &> /dev/null; then
    echo "OpenSSL is not installed. Please install it and try again."
    exit 1
fi

# Check if certificate files exist, if not, generate them
if [ ! -f "server.crt" ] || [ ! -f "server.key" ]; then
    echo "SSL certificate files not found. Generating self-signed certificates for testing..."
    openssl req -x509 -newkey rsa:4096 -keyout server.key -out server.crt -days 365 -nodes -subj "/CN=localhost"
    if [ $? -ne 0 ]; then
        echo "Failed to generate SSL certificates. Please check your OpenSSL installation."
        exit 1
    fi
    echo "Self-signed certificates generated successfully."
fi

# Run the p2p_node executable
if [ "$#" -lt 1 ] || [ "$#" -gt 3 ]; then
    echo "Usage: $0 <port> [peer_ip] [peer_port]"
    exit 1
fi

./build/p2p_node "$@"