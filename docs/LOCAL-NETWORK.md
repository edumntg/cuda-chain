# Local network: one server, many participants on the same Wi-Fi

This procedure runs a plasmon network inside one home or office network. One computer
runs the coordinator. Every other computer runs a trainer and connects to it. Any
computer can submit a job. No internet access is needed after the installation.

The example trains the MNIST classifier from `examples/mnist/job.yaml`. It works on CPUs.

Every step uses the `plasmon` command. For the version with exactly a Mac and a Windows
PC, see [HOME-LAB.md](HOME-LAB.md).

## Words used here

| Word | Meaning |
|---|---|
| server | the computer that runs the coordinator and the dashboard |
| participant | a computer that runs a trainer and offers its CPU or GPU |
| job | a model, a dataset and a recipe, submitted by one person and trained by the participants |

## Requirements

- All computers are on the same Wi-Fi or wired network, and can reach each other. Guest
  networks and some hotel or campus networks block this; use a home router or a phone
  hotspot if you are not sure.
- Python 3.11 or newer on every computer.
- About 2 GB of disk on every computer for PyTorch (CPU) and the data.
- The server keeps port 7117 open for the participants. The participants open no port.

## Step 1: find the address of the server

On the computer that will be the server:

| System | Command | Result looks like |
|---|---|---|
| macOS | `ipconfig getifaddr en0` (Wi-Fi) or `en1` | `192.168.1.20` |
| Windows | `ipconfig`, read "IPv4 Address" under the Wi-Fi adapter | `192.168.1.20` |
| Linux | `hostname -I` | `192.168.1.20` |

Write it down. The examples below use `192.168.1.20`. If your router gives a different
address later, participants must log in again with the new one. A DHCP reservation in the
router keeps the address fixed.

## Step 2: install the CLI and the engine on every computer

macOS and Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/edumntg/plasmon/main/install/install.sh | sh
python3 -m pip install "plasmon[engine] @ git+https://github.com/edumntg/plasmon.git"
```

Windows (PowerShell):

```powershell
powershell -c "irm https://raw.githubusercontent.com/edumntg/plasmon/main/install/install.ps1 | iex"
py -m pip install "plasmon[engine] @ git+https://github.com/edumntg/plasmon.git"
```

Open a new terminal window, then check on each computer:

```bash
plasmon --version
```

On Linux, install PyTorch for CPU first to avoid the CUDA download:
`python3 -m pip install torch --index-url https://download.pytorch.org/whl/cpu`.

Without the CLI binary, the same commands work as `python3 -m plasmon ...` or
`py -m plasmon ...`, without the live terminal views.

## Step 3: start the server

On the server:

```bash
plasmon server init --org home
plasmon server start
```

The server prints its addresses:

```
plasmon coordinator
  on this computer   http://localhost:7117
  from the network   http://192.168.1.20:7117   (best guess, see below)
  api                http://192.168.1.20:7117/api/docs
  data               /Users/you/Library/Application Support/plasmon/server
```

When the computer has several addresses, the server lists them with their interface
names. Participants use the Wi-Fi or wired one (`en0` on a Mac, `eth0` or `wlan0` on
Linux, "Wi-Fi" on Windows). Addresses on `utun`, `tun`, `vmnet`, `bridge` or `docker`
interfaces belong to a VPN or to virtual machines and do not answer. Publish the right one
with `plasmon server init --public-url http://192.168.1.20:7117`.

Keep this terminal open. Stop the server with `Ctrl+C`; it keeps all data and continues
at the next `server start`.

Firewall prompts:

- macOS asks "Do you want the application Python to accept incoming network
  connections?" Select **Allow**.
- Windows Defender Firewall shows a prompt for Python. Select **Private networks** and
  **Allow access**.
- Linux with ufw: `sudo ufw allow 7117/tcp`.

## Step 4: create the first account

On any computer, open `http://192.168.1.20:7117` in a browser. Select **Create
account**. The first account becomes the owner. Other people create their own accounts
the same way, or share one account at home.

## Step 5: connect the participants

On each participant (and on the server too, if it should train as well):

```bash
plasmon login --server http://192.168.1.20:7117
plasmon trainer start --name living-room-pc
```

Windows:

```powershell
plasmon login --server http://192.168.1.20:7117
plasmon trainer start --name office-laptop
```

`login` shows a code and opens the browser. Confirm the code in the browser. The trainer
then enrols the computer and waits for a round:

```
12:40:01 INFO enrolled machine 9f3a1c2b as living-room-pc
12:40:01 INFO trainer living-room-pc on http://192.168.1.20:7117, device cpu
```

Keep the terminal open, or install it as a service that starts at login:

```bash
plasmon trainer enable --name living-room-pc
```

Check the fleet from any logged-in computer, or on the dashboard (**Fleet**, owner or
operator). Each participant shows `idle`:

```bash
plasmon fleet
plasmon fleet --watch        # live; q leaves
```

## Step 6: submit a job

From any computer that is logged in:

```bash
git clone https://github.com/edumntg/plasmon.git
cd plasmon
plasmon job submit examples/mnist/job.yaml
```

Or open **Jobs**, **Submit a job** on the dashboard, and submit the prefilled text.

The job downloads MNIST once from a public mirror. Other sources (a CSV at a public URL,
files you downloaded, Fashion-MNIST) are in
[`examples/mnist/README.md`](../examples/mnist/README.md).

The command prints the job id and the dashboard page. Within seconds the participants
print lines like:

```
12:41:03 INFO round 0 of mnist-home: shard 17 (1000 samples)
12:41:06 INFO round 0 done: loss 2.301→0.412, 71,234 bytes up, fetch 0.3s train 2.1s upload 0.2s
```

## Step 7: watch

| What | Dashboard | Terminal |
|---|---|---|
| the job: loss, rounds, which computer trained each round | **Jobs**, then the job | `plasmon job watch <id>` |
| all participants: status, CPU, RAM, GPU, current round | **Fleet** | `plasmon fleet --watch` |
| one participant, with its log | **My machine** or **Fleet**, then the computer | `plasmon fleet show <node> --watch`, `plasmon fleet logs <node> -f` |
| everything on one screen | | `plasmon dashboard` |
| the server | **Server** | `plasmon server status --watch` |
| the signed record of every round | **Ledger** | `plasmon ledger verify` |

The node id of a participant is the first column of `plasmon fleet --json`.

Twenty rounds take two to five minutes on two or three CPUs.

## Step 8: get the model

```bash
plasmon job download <id> -o mnist.safetensors
python3 examples/mnist/eval.py mnist.safetensors
```

Expected: an accuracy between 96 % and 98 % on the 10,000 MNIST test images.

## Step 9: add, remove, pause

- A new participant joins at any time with step 5. It takes a round at the next round
  boundary.
- `Ctrl+C` in a trainer window removes that participant. Its current round expires and the
  round closes with the other updates.
- The owner pauses or drains a participant from its page or with
  `plasmon fleet pause|drain|resume <node>`.
- An availability policy for everyone (for example, train only at night) is set in
  **Settings** or with `plasmon policy set --windows "daily 22:00-07:00"`.

## Problems and solutions

| Problem | Check | Solution |
|---|---|---|
| The browser says "didn't send any data" or `ERR_EMPTY_RESPONSE` | Is the address on a `utun`, `vmnet` or `bridge` interface? | Use `http://localhost:7117` on the server itself and the Wi-Fi address from participants. A VPN on the server or the participant can also swallow local traffic; pause it to test. |
| `cannot reach http://192.168.1.20:7117` | On the participant: `curl http://192.168.1.20:7117/v1/healthz` | Both computers on the same network? Firewall on the server allows Python or port 7117? Address correct and unchanged? |
| The browser cannot open the dashboard from a participant, but the server can | Same as above | The server's firewall. Allow Python (macOS, Windows) or port 7117 (Linux). |
| The participant shows `offline` on the dashboard | Is `trainer start` still running? | Start it again, or install it as a service. |
| A participant shows `unavailable` | Its page shows the reason | Outside the policy window, or on battery. |
| The job stays at round 0 | **Fleet**: is at least one participant `idle`? | Start a trainer. `requirements.min_trainers` in the job must not exceed the number of participants. |
| `job submit` says `CERTIFICATE_VERIFY_FAILED` | Python does not trust the certificate of the download mirror | macOS with Python from python.org: run `Install Certificates.command` from the Python folder in Applications. Company proxy: set `SSL_CERT_FILE` to the company CA bundle, or `PLASMON_INSECURE_DOWNLOADS=1` for the built-in datasets (checked by MD5), or download the files with `curl` and use `examples/mnist/job-local.yaml`. |
| Rounds are slow | Participant log: the `train` time | The job's `inner_steps` and `batch_size` set the work per round. Lower them for slow computers. |
| The server address changed after a restart of the router | `ipconfig getifaddr en0` on the server | Participants run `login` again with the new address. Set a DHCP reservation to avoid this. |

## Scripts

The folder [`examples/local-network/`](../examples/local-network/) has shell scripts
that run the same commands for a server, a participant and a submission. They are for
automation; the steps above are the reference.

## Data and privacy on a local network

- The dataset shards, the model weights and the updates stay on the server and the
  participants. Nothing leaves the network.
- The connection is HTTP inside the local network. For a network with people you do not
  trust, run the server behind the TLS bundle described in
  [SELF-HOSTING.md](SELF-HOSTING.md).
- A participant sends hardware metrics and its own trainer log lines. Nothing else on
  the computer is read.
