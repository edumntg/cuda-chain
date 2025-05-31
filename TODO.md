# CPChain - TODO List

This document outlines the features to be implemented for the CPChain software, listed in order of priority.

## Phase 1: Core Infrastructure & Authentication

1.  **Project Setup & Basic CLI Structure:**
    *   Set up the Python project (virtual environment, dependencies for CLI and Server - e.g., FastAPI, uvicorn, requests, python-jose for JWT).
2.  **Server: Initial Setup:**
    *   Create basic FastAPI application structure. Define placeholder endpoints.
3.  **Server: User Model & DB:**
    *   Define User model (e.g., username, hashed_password). Set up SQLite database and basic CRUD operations for users (no API yet).
4.  **Server: Authentication Endpoints:**
    *   Implement `/register` and `/login` (token generation using JWT) endpoints.
5.  **CLI: Authentication:**
    *   Implement `cpchain login` to call the server's /login endpoint and store the token. Implement `cpchain register`.
6.  **Requester: Submit Training Request (to Server):**
    *   Define the structure of `metadata.json`.
    *   Implement `cpchain request metadata.json`:
        *   Basic validation of `metadata.json`.
        *   Send the request to a new `/requests/submit` endpoint on the Central Server (requires auth token).
7.  **Server: Request Model & Handling:**
    *   Define Request model (linking to user, storing metadata, status, batches). Implement `/requests/submit` endpoint to store new requests.
8.  **Worker: View Available Requests (from Server):**
    *   Implement `cpchain worker list_requests` command that queries a new `/requests/available` endpoint on the Central Server (requires auth token).
9.  **Server: List Available Requests:**
    *   Implement `/requests/available` endpoint to list requests not yet fully assigned or completed.
10. **Worker: Accept Training Request (via Server):**
    *   Implement `cpchain worker take_request <request_id>`:
        *   CLI sends request to a new `/requests/<request_id>/take_batch` endpoint on the server (requires auth token).
        *   Server assigns a specific batch to the worker, updates request status, and returns batch info.
11. **Server: Batch Assignment Logic:**
    *   Implement `/requests/<request_id>/take_batch` endpoint. It should manage assigning individual, unassigned batches to workers. Update status of request and batches.

## Phase 2: Simulated Training & P2P Data Transfer Setup

12. **Worker: Download Model & Dataset (Simulation):**
    *   Modify `take_request` (after server assigns a batch):
        *   Server response for `take_batch` should include URLs from `metadata.json`.
        *   CLI prints "Simulating download of model from [URL]" and "Simulating download of dataset for batch [X] from [URL]".
        *   (P2P data transfer will be a separate, later task).
13. **Worker: Simulate Training Process:**
    *   Further modify `take_request` to:
        *   Read batch information from `metadata.json` (provided by server in `take_batch` response).
        *   Simulate training on one batch (e.g., print "Training on batch X...", wait for a few seconds).
14. **Worker: Submit Trained Weights (Simulation):**
    *   After simulated training, CLI calls a new `/requests/<request_id>/batch_complete` endpoint on the server (with batch_id, status, and maybe a dummy link to 'weights').
15. **Server: Batch Completion:**
    *   Implement `/requests/<request_id>/batch_complete` endpoint to update the status of the batch and overall request.
16. **Requester: Check Request Status (from Server):**
    *   Implement `cpchain request status <request_id>` to query a `/requests/<request_id>/status` endpoint on the server.
17. **Server: Request Status Endpoint:**
    *   Implement `/requests/<request_id>/status` endpoint.
18. **P2P Data Transfer - Conceptual Design & Library Selection:**
    *   Research and decide on a P2P library/method for direct Requester-Worker data transfer (e.g., WebRTC data channels if clients can be browser-based in future, or direct TCP/UDP with NAT traversal considerations, or a library like `python-libp2p`). The server would broker the connection details.

## Phase 3: Actual Training & P2P Data Implementation

19. **Worker: P2P Model Downloading:**
    *   Implement actual model download from Requester/URL using the chosen P2P mechanism, coordinated by the server.
20. **Worker: P2P Dataset Batch Downloading:**
    *   Implement actual dataset batch download using P2P.
21. **Worker: Integrate a Basic Training Loop:**
    *   Define how a generic training script/function would be called by CPChain.
    *   For now, this might involve the user providing a script, and CPChain setting up the environment and calling it.
    *   Focus on a specific framework initially (e.g., TensorFlow/Keras or PyTorch).
22. **Worker: Handle Training Failures & Re-queuing:**
    *   If training fails, CLI calls a `/requests/<request_id>/batch_failed` endpoint on the server (with batch_id).
    *   Server re-queues the batch.
23. **Server: Batch Failure Handling:**
    *   Implement `/requests/<request_id>/batch_failed` to re-queue batches.
24. **Requester: P2P Download Trained Weights:**
    *   Implement P2P download of weights from Worker, coordinated by the server.
25. **Server: Request Expiry Logic:**
    *   Implement mechanism on the server to mark requests as expired if not fully completed within a timeframe (e.g., 24 hours for being taken, or longer for full completion).

## Phase 4: Advanced Features & Production Readiness

26. **Worker: Automatic Request Acceptance Configuration:**
    *   Allow Workers to define a configuration file (`worker_config.json`) with criteria for auto-accepting requests (e.g., max model size, allowed frameworks, min reward if/when incentives are added). The CLI would use this to decide which requests to ask the server for via `take_request`.
27. **Security & Validation:**
    *   Validate `metadata.json` more thoroughly (server-side).
    *   Consider security implications of running arbitrary model code (sandboxing?).
    *   Checksums for model/data integrity (server and client).
28. **Incentives/Reputation System (Conceptual):**
    *   Design a system to reward Workers (e.g., cryptocurrency, reputation points) - server-centric.
29. **Improved Peer-to-Peer Networking:**
    *   More robust peer discovery (e.g., DHT, bootstrap nodes for P2P connections, server may assist).
    *   Reliable message passing for P2P.
30. **Scalability & Performance:**
    *   Optimize network communication (CLI-server and P2P).
    *   Efficient storage and querying of requests on the server.
31. **Comprehensive Testing:**
    *   Unit tests, integration tests for all components (CLI, Server, P2P interactions).
32. **Packaging & Distribution:**
    *   Make the software easy to install (e.g., PyPI package for CLI, Docker for server).
33. **Detailed Documentation & User Guides:**
    *   Expand `README.md` and add more specific user guides for Requesters, Workers, and Server setup.
