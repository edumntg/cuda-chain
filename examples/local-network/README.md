# Local network scripts

Scripts for the procedure in [docs/LOCAL-NETWORK.md](../../docs/LOCAL-NETWORK.md): one
server and any number of participants on the same Wi-Fi. Each script prints what it does.

| Script | Where | What it does |
|---|---|---|
| `server.sh` | the server (macOS, Linux) | writes the configuration on the first run, prints the dashboard address, starts the coordinator |
| `join.sh <server-url> [name]` | each participant (macOS, Linux) | logs in to the server and starts a trainer |
| `join.ps1 <server-url> [name]` | each participant (Windows) | the same, for PowerShell |
| `submit.sh <server-url> [job.yaml]` | any computer | submits a job (default: the MNIST example) and follows it |

All scripts need the engine installed first:

```bash
python3 -m pip install "plasmon[engine] @ git+https://github.com/edumntg/plasmon.git"
```

Example, with the server at 192.168.1.20:

```bash
# on the server
./examples/local-network/server.sh

# on each participant
./examples/local-network/join.sh http://192.168.1.20:7117 living-room-pc

# from any computer
./examples/local-network/submit.sh http://192.168.1.20:7117
```
