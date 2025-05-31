# CPChain - TODO List

This document outlines the features to be implemented for the CPChain software, listed in order of priority.

## Phase 1: Core Network & Basic Functionality

1.  **Project Setup & Basic CLI Structure:**
    *   Set up the Python project (virtual environment, dependencies).
    *   Implement a basic CLI argument parser (e.g., using `argparse`) for top-level commands like `cpchain request` and `cpchain worker`.
2.  **Requester: Submit Training Request (Simplified):**
    *   Define the structure of `metadata.json`.
    *   Implement `cpchain request metadata.json`:
        *   Basic validation of `metadata.json`.
        *   Store the request locally (e.g., in a simple file-based queue or a lightweight database for now). This simulates "submitting to the network" for initial development.
3.  **Worker: View Available Requests (Simplified):**
    *   Implement a `cpchain worker list_requests` command that reads from the local request store.
4.  **Worker: Accept Training Request (Simplified):**
    *   Implement `cpchain worker take_request <request_id>`:
        *   Mark the request as "taken" in the local store.
        *   (Placeholder for download/train logic).
5.  **Networking - Basic Peer Discovery (Conceptual):**
    *   Research and decide on a basic peer-to-peer networking approach (e.g., simple sockets, a library like `libp2p` if feasible for Python).
    *   Implement a way for nodes to "find" each other on a local network initially.

## Phase 2: Training Simulation & Decentralization

6.  **Worker: Download Model & Dataset (Simulation):**
    *   Modify `take_request` to simulate downloading:
        *   Accept URLs in `metadata.json` but initially just print "Downloading model from [URL]" and "Downloading dataset from [URL]".
        *   No actual download/training yet.
7.  **Worker: Simulate Training Process:**
    *   Further modify `take_request` to:
        *   Read batch information from `metadata.json`.
        *   Simulate training on one batch (e.g., print "Training on batch X...", wait for a few seconds).
8.  **Worker: Submit Trained Weights (Simulation):**
    *   After simulated training, print "Submitting weights for batch X...".
    *   Store a dummy "weights file" or update the request status to "batch_complete".
9.  **Requester: Check Request Status (Simplified):**
    *   Implement `cpchain request status <request_id>` to view progress.
10. **Decentralized Request Propagation (Basic):**
    *   When a Requester submits a request, broadcast it to known peers.
    *   When a Worker starts, it should be able to receive these broadcasted requests.
11. **Decentralized Request Taking:**
    *   When a Worker takes a request, it should inform other peers so the request (or specific batch) is no longer advertised as available by them.

## Phase 3: Actual Training & Robustness

12. **Worker: Implement Actual Model Downloading:**
    *   Use libraries like `requests` or `urllib` to download model files.
13. **Worker: Implement Actual Dataset Downloading & Batching:**
    *   Handle dataset downloading.
    *   Implement logic to correctly access/load only the assigned batch of data.
14. **Worker: Integrate a Basic Training Loop:**
    *   Define how a generic training script/function would be called by CPChain.
    *   For now, this might involve the user providing a script, and CPChain setting up the environment and calling it.
    *   Focus on a specific framework initially (e.g., TensorFlow/Keras or PyTorch).
15. **Worker: Handle Training Failures & Re-queuing:**
    *   If the training script fails or the Worker is interrupted, the batch request should be re-queued in the network.
    *   Implement a timeout mechanism for Workers.
16. **Requester: Download Actual Trained Weights:**
    *   Implement a mechanism for Workers to make weights available (e.g., temporary hosting, direct transfer).
    *   Implement `cpchain request download_weights <request_id> <batch_id>`.
17. **Request Expiry:**
    *   Implement the 24-hour expiry for requests that are not taken.

## Phase 4: Advanced Features & Production Readiness

18. **Worker: Automatic Request Acceptance Configuration:**
    *   Allow Workers to define a configuration file (`worker_config.json`) with criteria for auto-accepting requests (e.g., max model size, allowed frameworks, min reward if/when incentives are added).
19. **Security & Validation:**
    *   Validate `metadata.json` more thoroughly.
    *   Consider security implications of running arbitrary model code (sandboxing?).
    *   Checksums for model/data integrity.
20. **Incentives/Reputation System (Conceptual):**
    *   Design a system to reward Workers (e.g., cryptocurrency, reputation points). This is a complex feature and might be out of scope for an initial MVP.
21. **Improved Peer-to-Peer Networking:**
    *   More robust peer discovery (e.g., DHT, bootstrap nodes).
    *   Reliable message passing.
22. **Scalability & Performance:**
    *   Optimize network communication.
    *   Efficient storage and querying of requests.
23. **Comprehensive Testing:**
    *   Unit tests, integration tests for all components.
24. **Packaging & Distribution:**
    *   Make the software easy to install (e.g., PyPI package).
25. **Detailed Documentation & User Guides:**
    *   Expand `README.md` and add more specific user guides.
