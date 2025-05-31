# CPChain - TODO List

This document outlines the features to be implemented for the CPChain software, listed in order of priority.
Items marked with "DONE - " are considered complete for their initial phase.

## Phase 1: Core Infrastructure & Authentication

DONE - 1.  **Project Setup & Basic CLI Structure:**
DONE -     *   Set up the Python project (virtual environment, dependencies for CLI and Server - e.g., FastAPI, uvicorn, requests, python-jose for JWT, click).
DONE -     *   Implement a basic CLI argument parser (e.g., using `click`) for top-level commands. (`cli/main.py`)
DONE -     *   Configuration management for server URL and token in CLI. (`cli/main.py`)

DONE - 2.  **Server: Initial Setup:**
DONE -     *   Create basic FastAPI application structure. (`backend/main.py`)
DONE -     *   Define placeholder endpoints. (Initial `backend/main.py` had this, now populated)

DONE - 3.  **Server: User Model & DB:**
DONE -     *   Define User model (e.g., username, hashed_password). (`backend/models/user.py`)
DONE -     *   Set up SQLite database and basic CRUD operations for users. (`backend/database.py`, `backend/crud/user.py`)

DONE - 4.  **Server: Authentication Endpoints:**
DONE -     *   Implement `/register` and `/login` (token generation using JWT) endpoints. (`backend/routers/auth.py`)

DONE - 5.  **CLI: Authentication:**
DONE -     *   Implement `cpchain auth login` to call the server's /login endpoint and store the token. (`cli/auth_commands.py`)
DONE -     *   Implement `cpchain auth register`. (`cli/auth_commands.py`)
DONE -     *   Implement `cpchain auth logout` and `cpchain auth whoami`. (`cli/auth_commands.py`)

DONE - 6.  **Requester: Submit Training Request (to Server):**
DONE -     *   Define the structure of `metadata.json` (implicitly by server's expectation).
DONE -     *   Implement `cpchain request submit metadata.json`: (`cli/requester_commands.py`)
DONE -         *   Basic validation of `metadata.json` (file existence, basic JSON load).
DONE -         *   Send the request to `/requests/` endpoint on the Central Server (requires auth token).

DONE - 7.  **Server: Request Model & Handling:**
DONE -     *   Define Request model (`TrainingRequest`, `RequestBatch`) linking to user, storing metadata, status, batches. (`backend/models/user.py`)
DONE -     *   Implement `/requests/` (POST) endpoint to store new requests and create associated batches. (`backend/routers/requests.py`, `backend/crud/request.py`)

DONE - 8.  **Worker: View Available Requests (from Server):**
DONE -     *   Implement `cpchain worker list-requests` command that queries `/worker/requests/available` endpoint. (`cli/worker_commands.py`)

DONE - 9.  **Server: List Available Requests:**
DONE -     *   Implement `/worker/requests/available` endpoint to list requests with pending batches. (`backend/routers/worker.py`, `backend/crud/request.py`)

DONE - 10. **Worker: Accept Training Request (via Server):**
DONE -     *   Implement `cpchain worker take-request <request_id>`: (`cli/worker_commands.py`)
DONE -         *   CLI sends request to `/worker/requests/<request_id>/take_batch` endpoint.
DONE -         *   Server assigns a specific batch, updates status, returns batch info.

DONE - 11. **Server: Batch Assignment Logic:**
DONE -     *   Implement `/worker/requests/<request_id>/take_batch` endpoint. (`backend/routers/worker.py`, `backend/crud/request.py`)
DONE -     *   Manages assigning individual, unassigned batches. Updates status.

## Phase 2: Simulated Training & P2P Data Transfer Setup (Backend parts mostly done for status updates)

DONE - 1.  **Worker: Simulate Download Model & Dataset (CLI prints placeholders):**
    *   Modify `take_request` (after server assigns a batch):
        *   Server response for `take_batch` should include URLs from `metadata.json`. (Server sends batch info, CLI would need to access metadata from it or make another call - *Partially done, CLI needs to show this*)
        *   CLI prints "Simulating download of model from [URL]" and "Simulating download of dataset for batch [X] from [URL]". (*To be added explicitly in CLI's take-request if not already there*)
    *   (P2P data transfer will be a separate, later task).

2.  **Worker: Simulate Training Process:**
    *   Further modify `take_request` or a new `process_batch` command to:
        *   Read batch information.
        *   Simulate training on one batch (e.g., print "Training on batch X...", wait for a few seconds).

DONE - 3.  **Worker: Submit Trained Weights (Simulation - status update):**
DONE -     *   After simulated training, CLI calls `/worker/batch/<batch_id>/complete` or `/failed` endpoint. (`cli/worker_commands.py`)

DONE - 4.  **Server: Batch Completion/Failure Handling:**
DONE -     *   Implement `/worker/batch/<batch_id>/complete` and `/failed` endpoints to update batch status. (`backend/routers/worker.py`)
DONE -     *   Server re-queues failed batches by setting status to PENDING.

DONE - 5.  **Requester: Check Request Status (from Server):**
DONE -     *   Implement `cpchain request status <request_id>` to query `/requests/<request_id>/status`. (`cli/requester_commands.py`)

DONE - 6.  **Server: Request Status Endpoint:**
DONE -     *   Implement `/requests/<request_id>/status` endpoint. (`backend/routers/requests.py`)

7.  **P2P Data Transfer - Conceptual Design & Library Selection:**
    *   Research and decide on a P2P library/method for direct Requester-Worker data transfer (e.g., WebRTC data channels, direct TCP/UDP with NAT traversal, or a library like `python-libp2p`). The server would broker connection details.

## Phase 3: Actual Training & P2P Data Implementation

1.  **Worker: P2P Model Downloading:**
    *   Implement actual model download from Requester/URL using the chosen P2P mechanism, coordinated by the server.
2.  **Worker: P2P Dataset Batch Downloading:**
    *   Implement actual dataset batch download using P2P.
3.  **Worker: Integrate a Basic Training Loop:**
    *   Define how a generic training script/function would be called by CPChain.
    *   This might involve the user providing a script, and CPChain setting up the environment and calling it.
    *   Focus on a specific framework initially (e.g., TensorFlow/Keras or PyTorch).
4.  **Worker: Handle Training Failures & Re-queuing (Advanced):**
    *   If the training script fails (not just CLI reporting), the batch request should be re-queued.
    *   Implement a timeout mechanism for Workers on the server side.
5.  **Requester: Download Actual Trained Weights (P2P):**
    *   Implement P2P download of weights from Worker, coordinated by the server.
DONE - 6.  **Server: Request Expiry Logic (Conceptual - can be basic cron or background task):**
    *   Implement mechanism on the server to mark requests as expired if not fully completed within a timeframe (e.g., 24 hours for being taken, or longer for full completion). (*Not explicitly implemented as an automated task, but statuses allow manual check*). -> *Needs actual implementation.*

## Phase 4: Advanced Features & Production Readiness

1.  **Worker: Automatic Request Acceptance Configuration:**
    *   Allow Workers to define a configuration file (`worker_config.json`) with criteria for auto-accepting requests.
2.  **Security & Validation (Ongoing):**
    *   Validate `metadata.json` more thoroughly on the server.
    *   Consider security implications of running arbitrary model code (sandboxing?).
    *   Checksums for model/data integrity.
3.  **Incentives/Reputation System (Conceptual):**
    *   Design a system to reward Workers.
4.  **Improved Peer-to-Peer Networking:**
    *   More robust peer discovery (e.g., DHT, bootstrap nodes) if moving away from server-brokering for some aspects.
    *   Reliable message passing for P2P.
5.  **Scalability & Performance:**
    *   Optimize database queries.
    *   Optimize network communication.
    *   Consider asynchronous tasks for long-running operations on the server.
6.  **Comprehensive Testing:**
    *   Unit tests for backend CRUD, logic.
    *   Integration tests for API endpoints.
    *   CLI command tests.
7.  **Packaging & Distribution:**
    *   Make the software easy to install (e.g., PyPI package for CLI, Docker for server).
8.  **Detailed Documentation & User Guides (Ongoing - this plan addresses part of it):**
    *   Expand `README.md` and add more specific user guides.
9.  **Server: Background Tasks for Maintenance:**
    *   Implement request expiry (actual cleanup).
    *   Orphaned batch cleanup.
10. **CLI: Enhanced Output & Interactivity:**
    *   Progress bars for simulated (and later actual) downloads/training.
    *   More detailed error reporting.
11. **Server: Overall Request Status Updates:**
    *  Automated logic to update `TrainingRequest.status` based on changes in `RequestBatch.status` (e.g. when a batch completes, check if all batches are complete to set overall request to COMPLETED). Currently, this is mostly manual or hinted at in comments.
