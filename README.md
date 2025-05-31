# CPChain: Decentralized AI Model Training Network

CPChain is a command-line software that implements a decentralized network for training AI models. It connects users who need computational power for training their models (Requesters) with users who can provide that power (Workers).

## Features

### For Requesters

*   **Submit Training Requests:** Requesters can submit AI model training jobs to the network using a JSON metadata file. This file specifies all necessary details, including:
    *   Model URL (link to the model architecture and initial weights)
    *   Dataset URL (link to the training data)
    *   Training parameters (epochs, learning rate, loss function, optimizer)
    *   Batch information (how the dataset is divided into batches)
*   **Request Lifecycle:**
    *   Requests are submitted to the network via the CLI (e.g., `cpchain request metadata.json`).
    *   Requests remain active in the network for 24 hours.
    *   If a request is not taken by a Worker within 24 hours, it is discarded.
*   **Download Trained Models:** Once a Worker successfully trains a model on an assigned batch, the updated weights are submitted back to the network. The Requester can then download these weights.

### For Workers

*   **Join the Network:** Users can join the CPChain network as Workers to offer their computational resources.
*   **Process Training Requests:**
    *   **Manual Acceptance:** Workers can view available training requests and manually choose which ones to accept.
    *   **Automatic Acceptance (Future Feature):** Workers will be able to configure criteria (e.g., model size, dataset type, reward) to automatically accept matching requests.
*   **Batch-wise Training:**
    *   When a Worker accepts a request, the CPChain software automatically downloads the specified model and the relevant dataset batch.
    *   The Worker's machine then trains the model on that specific batch. For example, if a Requester submits a job to train a model on a dataset divided into 10 batches, the first Worker to accept the request will train on batch 1, the second on batch 2, and so on.
*   **Submit Trained Weights:** After successfully completing the training for a batch, the Worker submits the updated model weights back to the network.
*   **Fault Tolerance:** If a Worker fails to complete training for a specific batch (due to error or interruption), the request for that batch is re-queued in the network for other Workers to pick up.

## Core Idea

CPChain aims to create a decentralized marketplace for AI model training. This approach allows:

*   **Accessibility:** Requesters without powerful local hardware can access the necessary computational resources.
*   **Efficiency:** Training tasks can be parallelized by distributing batches across multiple Workers.
*   **Resource Utilization:** Individuals and organizations can monetize their idle computing power by participating as Workers.

## Software Architecture

CPChain will employ a hybrid architecture, combining a Central Server for coordination and authentication with direct Peer-to-Peer (P2P) communication for efficient data handling once tasks are assigned.

### Components

1.  **Central Server:**
    *   **Purpose:** Manages user accounts, authenticates users, brokers training requests, and maintains a list of available tasks and active workers.
    *   **Technology Stack (Tentative):**
        *   Backend Framework: Python with FastAPI
        *   Database: SQLite (for initial development, potentially PostgreSQL/MongoDB later)
        *   Authentication: JWT (JSON Web Tokens) for session management.
    *   **Responsibilities:**
        *   **User Management:** Handles user registration and login. Issues authentication tokens to clients.
        *   **Request Brokering:**
            *   Requesters submit their `metadata.json` to this server.
            *   The server validates and lists new requests.
            *   Workers query the server for available requests.
            *   The server assigns a specific batch of a request to a Worker when they accept a task.
        *   **Status Tracking:** Keeps track of which Worker is assigned to which batch and the status of each batch (e.g., pending, in-progress, completed, failed).
        *   **Result Notification:** Notifies the Requester when batches are completed and weights are available.

2.  **CPChain Client (CLI):**
    *   **Purpose:** The command-line interface used by both Requesters and Workers to interact with the CPChain network.
    *   **Technology Stack (Tentative):**
        *   Language: Python
        *   Libraries: `requests` (for server communication), `argparse`/`click` (for CLI).
    *   **Responsibilities:**
        *   **Authentication:** Communicates with the Central Server to log users in and obtain session tokens. Securely stores and uses this token for subsequent requests.
        *   **Requester Functions:**
            *   `cpchain login`: Authenticates the user with the Central Server.
            *   `cpchain request metadata.json`: Submits the training job details to the Central Server.
            *   `cpchain request status <request_id>`: Queries the Central Server for the status of a submitted request.
            *   `cpchain request download <request_id> [batch_id]`: (Potentially) Initiates download of trained weights, possibly directly from the Worker via P2P after server coordination.
        *   **Worker Functions:**
            *   `cpchain login`: Authenticates the user with the Central Server.
            *   `cpchain worker join_network`: Registers the client as an active Worker with the Central Server.
            *   `cpchain worker list_requests`: Fetches a list of available training tasks from the Central Server.
            *   `cpchain worker take_request <request_id>`: Signals intent to take a specific request (or the next available batch of it) to the Central Server. The server then assigns a specific batch.
            *   **Task Execution:**
                *   Downloads model and dataset batch (potentially P2P after coordination).
                *   Runs the training process.
                *   Submits updated weights (potentially P2P after coordination) and completion status to the Central Server.
            *   `cpchain worker leave_network`: Signals the Central Server that the worker is going offline.

3.  **Peer-to-Peer (P2P) Communication Layer:**
    *   **Purpose:** Facilitates direct data transfer between Requesters and Workers (or Worker-to-Worker if future features require it) for large files like models, datasets, and trained weights. This offloads bandwidth from the Central Server.
    *   **Technology Stack (Tentative):**
        *   Could range from direct HTTP/TCP connections initiated after server handshaking, to more advanced P2P libraries (e.g., `python-libp2p` if suitable, or custom socket programming). The exact choice will depend on requirements like NAT traversal.
    *   **Responsibilities:**
        *   **Data Transfer:** Once the Central Server assigns a task to a Worker, it can provide connection details (e.g., IP/port of the Worker, or a temporary P2P ID) to the Requester (or vice-versa) to establish a direct link for transferring the model/dataset to the Worker, and later for the Worker to send back the trained weights.
        *   The server would still be notified of the transfer completion.

### Workflow Example (Simplified)

1.  **User Login:** Both Requester and Worker log in via `cpchain login`. The CLI contacts the Central Server, which authenticates and returns a token.
2.  **Request Submission:** Requester uses `cpchain request metadata.json`. The CLI sends the metadata and token to the Central Server. The server lists the request.
3.  **Worker Discovery:** Worker uses `cpchain worker list_requests`. The CLI contacts the server (with token) to get available tasks.
4.  **Task Acceptance:** Worker uses `cpchain worker take_request <request_id>`. The CLI informs the server. The server assigns a specific batch to this Worker and marks it as "in-progress". The server might also provide P2P connection info for the Requester (or a relay mechanism).
5.  **Data Download (P2P):** The Worker's client uses the provided info to download the model and specific data batch, potentially directly from the Requester's machine or a URI they provided.
6.  **Training:** Worker client trains the model on the batch.
7.  **Weight Upload (P2P & Server):** Worker client uploads the trained weights (potentially directly to the Requester or a temporary P2P storage) and notifies the Central Server of completion and the location/means to access the weights.
8.  **Result Retrieval:** Requester sees the updated status via `cpchain request status` and can then download the weights.

This hybrid approach aims to leverage the Central Server for reliable coordination and user management while using P2P for scalable and efficient transfer of large data.

## Getting Started

(This section will be updated as the project develops, including installation instructions and detailed command usage.)
