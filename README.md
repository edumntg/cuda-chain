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

## Getting Started

(This section will be updated as the project develops, including installation instructions and detailed command usage.)
