# Quickstart: one machine

This procedure runs the coordinator, one trainer and one training job on the same
computer. Use it to see the full cycle in ten minutes. For several computers on one
Wi-Fi, see [LOCAL-NETWORK.md](LOCAL-NETWORK.md). For exactly a Mac and a Windows PC, see
[HOME-LAB.md](HOME-LAB.md). For a company server, see [SELF-HOSTING.md](SELF-HOSTING.md).

## Requirements

- Python 3.11 or newer.
- 2 GB of free disk space. PyTorch for CPU is about 200 MB; MNIST is 11 MB.
- An open TCP port. The default is 7117.

A GPU is optional. The example job trains a small CNN on MNIST on a CPU in a few minutes.

## Step 1: install the CLI and the engine

```bash
curl -fsSL https://raw.githubusercontent.com/edumntg/plasmon/main/install/install.sh | sh    # Linux, macOS
python -m pip install "plasmon[engine] @ git+https://github.com/edumntg/plasmon.git"
```

Windows, in PowerShell: `irm https://raw.githubusercontent.com/edumntg/plasmon/main/install/install.ps1 | iex`
and `py -m pip install "plasmon[engine] @ git+https://github.com/edumntg/plasmon.git"`.

On Linux, install PyTorch for CPU first to avoid the CUDA download:

```bash
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
```

Open a new terminal and check the installation:

```bash
plasmon --version
```

Every `plasmon` command below also works as `python -m plasmon`, without the live views.

## Step 2: start the coordinator

```bash
plasmon server init
plasmon server start
```

The server prints its addresses. On this computer, use `http://localhost:7117`. Keep this
terminal open.

## Step 3: create the owner account

Open `http://localhost:7117` in a browser. Select **Create account**. The first account on
a server becomes the owner.

## Step 4: log in from the command line

Open a second terminal:

```bash
plasmon login --server http://127.0.0.1:7117
```

The command shows a code and opens the browser. Confirm the code in the browser. The
command line is now logged in.

## Step 5: start a trainer

```bash
plasmon trainer start --name my-pc
```

The trainer enrols the machine and waits for a round. Keep this terminal open. The
machine appears on the dashboard under **My machine**.

## Step 6: submit the job

Open a third terminal:

```bash
git clone https://github.com/edumntg/plasmon.git
cd plasmon
plasmon job submit examples/mnist/job.yaml
```

The command uploads the initial weights and the data shards, then prints the job id.

## Step 7: watch

```bash
plasmon job watch <job id>
```

The screen shows the loss per round, the rounds table and the trainer. Press `q` to
leave; the job continues. The dashboard page **Jobs** shows the same data as a chart.
`plasmon fleet --watch` shows the machine, `plasmon dashboard` shows everything.

## Step 8: download and test the model

```bash
plasmon job download <job id> -o mnist.safetensors
python examples/mnist/eval.py mnist.safetensors
```

The second command prints the accuracy on the 10,000 MNIST test images.

## Where the files are

| What | Where |
|---|---|
| Server configuration | `plasmon-server.yaml` in the server data directory (printed by `server start`) |
| Database and blobs | the server data directory |
| Your login | `credentials.toml` in the plasmon configuration directory |
| Machine key | `machine.key` in the plasmon configuration directory |
| Datasets and blob cache | the plasmon cache directory |

Set `PLASMON_CONFIG_DIR`, `PLASMON_DATA_DIR` or `PLASMON_CACHE_DIR` to change these.

## Stop and clean up

- Stop a trainer or the server with `Ctrl+C`.
- Remove the server data directory to reset the server. All accounts, jobs and blobs are
  deleted.
