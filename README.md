# cuda-chain
A P2P network for distributed computing using CUDA Kernels.

## Core Features
- **Node Management:** Allows nodes to join and leave the network, and provides a mechanism for discovering other nodes in the network.
- **Job Management:** Enables users to submit computing jobs to the network, and manages the distribution and execution of these jobs across available nodes.
- **Data Management:** Handles the transfer and storage of data required for job execution, ensuring that data is available to the nodes that need it.

## CLI Specification
- `cuda-chain join [bootstrap_node_ip]`: Connects to the P2P network. If `bootstrap_node_ip` is provided, it connects to that specific node. Otherwise, it attempts to discover nodes on the local network.
- `cuda-chain leave`: Disconnects from the P2P network.
- `cuda-chain submit-job [kernel_file_path] [data_file_path]`: Submits a job to the network. `kernel_file_path` is the path to the CUDA kernel file, and `data_file_path` is the path to the input data file.
- `cuda-chain job-status [job_id]`: Checks the status of a submitted job.
- `cuda-chain list-nodes`: Lists all nodes currently connected to the network.
- `cuda-chain list-jobs`: Lists all jobs currently being processed by the network.
