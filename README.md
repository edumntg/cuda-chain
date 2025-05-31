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

## CLI Usage Examples

This section provides examples for common CPChain CLI commands. Ensure you have logged in using \`cpchain auth login\` before running commands that require authentication.

### Configuration

**1. Configure Server URL**

Set the backend server URL. This is typically done once.

\`\`\`bash
cpchain configure http://localhost:8000
\`\`\`
Output:
\`\`\`
Server URL configured to: http://localhost:8000
\`\`\`

View current server URL:
\`\`\`bash
cpchain configure
\`\`\`
Output:
\`\`\`
Current Server URL: http://localhost:8000
\`\`\`

### Authentication (\`auth\`)

**1. Register a New User**

\`\`\`bash
cpchain auth register --username youruser --password yourpass
\`\`\`
Output (on success):
\`\`\`
User 'youruser' registered successfully with ID: 1.
\`\`\`
If username is taken:
\`\`\`
Error: Registration failed. Username might be taken.
\`\`\`

**2. Login**

\`\`\`bash
cpchain auth login --username youruser --password yourpass
\`\`\`
Output:
\`\`\`
Login successful. Token stored for user 'youruser'.
\`\`\`

**3. Check Current User (whoami)**

Verify login status and token validity.
\`\`\`bash
cpchain auth whoami
\`\`\`
Output (if logged in and token is valid):
\`\`\`
Logged in as: youruser (ID: 1)
Token is valid.
\`\`\`
Output (if not logged in):
\`\`\`
You are not logged in.
\`\`\`

**4. Logout**
\`\`\`bash
cpchain auth logout
\`\`\`
Output:
\`\`\`
User 'youruser' logged out successfully.
\`\`\`

### Requester Commands (\`request\`)

**1. Submit a Training Request**

First, create a \`metadata.json\` file, for example:
\`\`\`json
{
  "name": "My Image Classification Model",
  "description": "Train a ResNet50 on CIFAR-10",
  "model_url": "http://example.com/models/resnet50_initial_weights.h5",
  "dataset_url": "http://example.com/datasets/cifar10_batches.zip",
  "num_batches": 10,
  "training_parameters": {
    "epochs": 5,
    "learning_rate": 0.001,
    "optimizer": "adam",
    "loss_function": "categorical_crossentropy"
  }
}
\`\`\`

Then, submit it:
\`\`\`bash
cpchain request submit ./metadata.json
\`\`\`
Output:
\`\`\`
Training request submitted successfully!
Request ID: 1
Status: pending
Number of batches created: 10
\`\`\`
Ensure \`num_batches\` is a positive integer in your metadata.

**2. Check Request Status**

\`\`\`bash
cpchain request status 1
\`\`\`
Output (example):
\`\`\`
Status for Request ID: 1
  Overall Status: pending
  Created At: 2023-10-27T10:00:00.123456+00:00
  Updated At: N/A
  Metadata: {
    "name": "My Image Classification Model",
    "description": "Train a ResNet50 on CIFAR-10",
    "model_url": "http://example.com/models/resnet50_initial_weights.h5",
    "dataset_url": "http://example.com/datasets/cifar10_batches.zip",
    "num_batches": 10,
    "training_parameters": {
      "epochs": 5,
      "learning_rate": 0.001,
      "optimizer": "adam",
      "loss_function": "categorical_crossentropy"
    }
  }
  Batches (10 total):
    - Batch Number: 1
      Batch ID: 1
      Status: pending
      Assigned Worker ID: N/A
      Assigned At: N/A
      Completed At: N/A
    - Batch Number: 2
      Batch ID: 2
      Status: pending
      Assigned Worker ID: N/A
      Assigned At: N/A
      Completed At: N/A
    ... (and so on for all batches)
\`\`\`

### Worker Commands (\`worker\`)

**1. List Available Requests**

List requests that have batches available for processing.
\`\`\`bash
cpchain worker list-requests
\`\`\`
Output (example):
\`\`\`
Available Training Requests:
  Request ID: 1
    Status: pending
    Created At: 2023-10-27T10:00:00.123456+00:00
    Total Batches: 10
--------------------
  Request ID: 2
    Status: partially_assigned
    Created At: 2023-10-27T10:05:00.789101+00:00
    Total Batches: 5
--------------------
\`\`\`
You can use \`--skip\` and \`--limit\` for pagination.

**2. Take a Request Batch**

A worker can take the next available batch from a specific request.
\`\`\`bash
cpchain worker take-request 1
\`\`\`
Output (example, if batch 1 of request 1 was taken):
\`\`\`
Successfully assigned to batch:
  Batch ID: 1
  Batch Number: 1
  For Request ID: 1
  Status: assigned
  Assigned Worker ID (You): 2
\`\`\`
(Assuming the worker who ran this is User ID 2)

**3. Update Batch Status**

After processing, a worker updates the batch status.

Mark as completed:
\`\`\`bash
cpchain worker update-batch-status 1 completed
\`\`\`
(Where '1' is the Batch ID received from \`take-request\`)
Output:
\`\`\`
Batch 1 status successfully updated to 'completed'.
  New Batch Status: completed
\`\`\`

Mark as failed (this will re-queue the batch for others):
\`\`\`bash
cpchain worker update-batch-status 2 failed
\`\`\`
(Where '2' is another Batch ID)
Output:
\`\`\`
Batch 2 status successfully updated to 'failed'.
  New Batch Status: pending
  Note: This batch should now be available for other workers if re-queued as PENDING.
\`\`\`
---

## Backend Server Setup & Usage

This section explains how to set up and run the CPChain backend server.

### Prerequisites

*   Python 3.8+
*   A virtual environment manager (e.g., \`venv\`, \`conda\`)

### Setup Instructions

1.  **Navigate to the Backend Directory:**
    If you have cloned the repository, change to the backend directory:
    \`\`\`bash
    cd path/to/cpchain/backend
    \`\`\`
    (Assuming you are in the root of the project where \`backend\` and \`cli\` directories reside)

2.  **Create and Activate a Virtual Environment:**
    It's highly recommended to use a virtual environment.
    \`\`\`bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    \`\`\`

3.  **Install Dependencies:**
    Install all required Python packages.
    \`\`\`bash
    pip install -r requirements.txt
    \`\`\`

4.  **Environment Variables:**
    The server requires certain environment variables. Create a \`.env\` file in the \`backend\` directory by copying the example:
    \`\`\`bash
    cp .env.example .env
    \`\`\`
    Now, edit the \`.env\` file and set a strong \`SECRET_KEY\`:
    \`\`\`dotenv
    # backend/.env
    SECRET_KEY=your_very_strong_random_secret_key_for_jwt_at_least_32_characters

    # The database URL defaults to SQLite in the backend directory.
    # SQLALCHEMY_DATABASE_URL=sqlite:///./cpchain.db

    # For PostgreSQL (example, if you set it up):
    # SQLALCHEMY_DATABASE_URL=postgresql://youruser:yourpassword@localhost:5432/cpchain_db
    \`\`\`
    **Important:** The \`SECRET_KEY\` is crucial for security (signing JWTs). Make it long, random, and keep it secret.

### Running the Server

Once the setup is complete, you can run the FastAPI server using Uvicorn:

\`\`\`bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
\`\`\`

*   \`main:app\`: Tells Uvicorn to find the FastAPI application instance named \`app\` in the \`main.py\` file.
*   \`--reload\`: Enables auto-reloading the server when code changes (useful for development).
*   \`--host 0.0.0.0\`: Makes the server accessible from other machines on your network (not just \`localhost\`).
*   \`--port 8000\`: Specifies the port to run on.

The server should now be running, and you'll see output indicating this, including the address (e.g., \`http://0.0.0.0:8000\`). The SQLite database file (\`cpchain.db\`) will be created in the \`backend\` directory automatically on first run if it doesn't exist, due to the startup event handler in \`main.py\`.

### Accessing API Documentation

With the server running, FastAPI automatically provides interactive API documentation:

*   **Swagger UI:** Open your browser and navigate to \`http://localhost:8000/docs\`
*   **ReDoc:** Open your browser and navigate to \`http://localhost:8000/redoc\`

These interfaces allow you to view all available API endpoints, their parameters, request/response models, and even try them out directly from your browser.

---

## Getting Started

(This section will be updated as the project develops, including installation instructions and detailed command usage.)
