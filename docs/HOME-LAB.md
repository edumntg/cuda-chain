# Home lab: a Mac and a Windows PC

This procedure trains an MNIST classifier on two computers at home with the `plasmon`
command. The Mac runs the coordinator and one trainer. The Windows PC runs a second
trainer. You submit the job from the Mac and watch it on both.

The same steps work with the roles reversed. For more computers, see
[LOCAL-NETWORK.md](LOCAL-NETWORK.md).

## Before you start

- Both computers are on the same Wi-Fi.
- Python 3.11 or newer is installed on both.
  - Mac: `brew install python@3.12`, or the installer from python.org.
  - Windows: the installer from python.org. Select **Add python.exe to PATH**.
- You know the IP address of the Mac. In Terminal: `ipconfig getifaddr en0`. The examples
  use `192.168.1.20`.
- No GPU is required. The job trains on CPU in a few minutes. A Mac with Apple Silicon
  uses its GPU through Metal automatically.

Every step below uses the `plasmon` command. If you skip the CLI install, the same
commands work as `python3 -m plasmon ...` (Mac) or `py -m plasmon ...` (Windows), without
the live terminal views.

## Part A: the Mac, server and first trainer

### A1. Install the CLI and the engine

```bash
curl -fsSL https://raw.githubusercontent.com/edumntg/plasmon/main/install/install.sh | sh
python3 -m pip install "plasmon[engine] @ git+https://github.com/edumntg/plasmon.git"
```

Open a new Terminal window so `plasmon` is on the PATH, then check:

```bash
plasmon --version
python3 -m plasmon --version
```

Both print `plasmon 0.1.2`.

To update later, when the repository has changed, update the two parts. The CLI binary:

```bash
curl -fsSL https://raw.githubusercontent.com/edumntg/plasmon/main/install/install.sh | sh
```

(Windows: `irm https://raw.githubusercontent.com/edumntg/plasmon/main/install/install.ps1 | iex`.)
The engine:

```bash
python3 -m pip install --force-reinstall --no-deps "plasmon[engine] @ git+https://github.com/edumntg/plasmon.git"
```

`plasmon --version` shows the binary; `python3 -m plasmon --version` shows the engine. Both
must show the new version. Then stop and start `plasmon server start` and each
`plasmon trainer start`: a running process keeps the old code, and the dashboard footer
shows the version of the running server. If the two versions differ, the CLI starts the
engine with the first `python3` on PATH that imports plasmon; `PLASMON_PYTHON` points it to
another interpreter.

### A2. Start the coordinator

```bash
plasmon server init --org home
plasmon server start
```

Output:

```
plasmon coordinator
  dashboard  http://192.168.1.20:7117
  api        http://192.168.1.20:7117/api/docs
  data       /Users/you/Library/Application Support/plasmon/server
```

Keep this window open. If macOS asks "Do you want the application Python to accept
incoming network connections?", select **Allow**.

### A3. Create the owner account

On the Mac, open `http://localhost:7117` in a browser. Select **Create account**. The
first account becomes the owner.

### A4. Log in from Terminal

Open a second Terminal window:

```bash
plasmon login --server http://192.168.1.20:7117
```

The command prints a code and opens the browser. Confirm the code. Then create the
machine key of the Mac and check both:

```bash
plasmon init
plasmon whoami
```

```
created machine key: /Users/you/Library/Application Support/plasmon/machine.key
node id: 9f3a1c2b…
server:  http://192.168.1.20:7117
user:    you@example.com (owner)
```

The node id identifies this computer in the fleet. `trainer start` creates the key too
when it is missing.

### A5. Start the first trainer

In the same window:

```bash
plasmon trainer start --name mac
```

```
12:40:01 INFO enrolled machine 9f3a1c2b as mac
12:40:01 INFO trainer mac on http://192.168.1.20:7117, device mps
```

Keep this window open. The Mac now waits for a round.

## Part B: the Windows PC, second trainer

### B1. Install the CLI and the engine

Open a normal PowerShell window (not "Run as administrator": the CLI installs into your
own user folder):

```powershell
irm https://raw.githubusercontent.com/edumntg/plasmon/main/install/install.ps1 | iex
py -m pip install "plasmon[engine] @ git+https://github.com/edumntg/plasmon.git"
```

From `cmd` instead of PowerShell, run the first line as
`powershell -c "irm https://raw.githubusercontent.com/edumntg/plasmon/main/install/install.ps1 | iex"`.

If `git` is not installed, install it from https://git-scm.com first. Open a new
PowerShell window, then check:

```powershell
plasmon --version
py -m plasmon --version
```

### B2. Log in

```powershell
plasmon login --server http://192.168.1.20:7117
```

Confirm the code in the browser. Log in with the account you created on the Mac, or
create a second account for the person who owns this PC.

### B3. Start the trainer

```powershell
plasmon trainer start --name windows
```

If Windows Firewall shows a prompt for Python, select **Allow**. The trainer opens only
outgoing connections. The PC now waits for a round.

## Part C: check the fleet

On the Mac, open a third Terminal window:

```bash
plasmon fleet
```

```
machine  owner            status  gpu        gpu%  cpu%  ram%  job / round  honesty  seen
mac      you@example.com  idle    Apple GPU        12    41                 1.00     3 s
windows  you@example.com  idle    none             8     55                 1.00     5 s
```

Both machines show `idle`. For the live version, press `q` to leave it:

```bash
plasmon fleet --watch
```

## Part D: submit the job

In the third Terminal window:

```bash
git clone https://github.com/edumntg/plasmon.git
cd plasmon
plasmon job submit examples/mnist/job.yaml
```

```
initial weights: mnist_cnn seed 0
dataset: MNIST (downloading on first use)
shards: 60 × 1000 samples, eval 1000 samples
uploading 62 of 62 blobs (47.6 MB); the rest is already on the server
submitted mnist-home as job_3f2a9c1e0b7d
  rounds: 20  shards: 60  params: 44,426
  watch: plasmon job watch job_3f2a9c1e0b7d
  page:  http://192.168.1.20:7117/jobs/job_3f2a9c1e0b7d
```

The job downloads MNIST once, from a public mirror, and keeps it on the server as 60
shards; the trainers fetch one shard per round. To use a CSV from a public URL, a copy you
downloaded yourself, or Fashion-MNIST, see
[`examples/mnist/README.md`](../examples/mnist/README.md).

Within a few seconds the two trainer windows print lines like:

```
12:41:03 INFO round 0 of mnist-home: shard 17 (1000 samples)
12:41:06 INFO round 0 done: loss 2.301→0.412, 71,234 bytes up, fetch 0.3s train 2.1s upload 0.2s
```

## Part E: watch

Follow the job in the third window. The screen shows the loss per round, the rounds table
and which machine trained each round. Press `q` to leave; the job continues.

How the two machines share the work: when a round opens, every idle machine that fits
the job takes a shard of it. The server does not close a round with fewer trainers than
there are idle machines until the slower one had two idle polls to join (about 8 seconds),
so a fast Mac does not take every round alone. Between rounds a machine is idle for a few
seconds; the dashboard keeps it in the job's box and shows "between rounds", and the fleet
table shows "round 7 of mnist-home done, waiting for the next". The job page explains a
real wait with a sentence such as "1 idle machine does not meet the job requirements".

```bash
plasmon job watch job_3f2a9c1e0b7d
```

Other views, each one live:

```bash
plasmon fleet --watch                       # both machines: status, CPU, RAM, current round
plasmon fleet show <node id> --watch        # one machine: gauges, sparkline, log tail
plasmon fleet logs <node id> -f             # one machine's log, followed
plasmon dashboard                           # one screen with tabs: j jobs, f fleet, m my machines, s server
plasmon server status                       # the coordinator: database, blobs, ledger, counts
plasmon job status job_3f2a9c1e0b7d         # the rounds table, once
```

The node id is the first column of `plasmon fleet --json`. In the browser, the job page,
**Fleet**, **My machine** and **Ledger** show the same data.

Twenty rounds take two to four minutes on the two CPUs.

## Part F: download and test the model

On the Mac, from the terminal:

```bash
plasmon job download job_3f2a9c1e0b7d -o mnist.safetensors
python3 examples/mnist/eval.py mnist.safetensors
```

Or select **Download latest weights** on the job page and run `eval.py` on the saved
file.

Expected after twenty rounds: an accuracy between 96 % and 98 % on the 10,000 test
images.

Check the signed record of the run:

```bash
plasmon ledger verify
```

```
ledger ok: true  entries: 22
```

## Part G: run the trainers at login (optional)

On each computer, replace the `trainer start` window with a service that starts at login:

```bash
plasmon trainer enable --name mac               # Mac: launchd agent
```

```powershell
plasmon trainer enable --name windows           # Windows: scheduled task
```

Add `--hours "daily 22:00-07:00"` to train only at night. Remove the service with
`plasmon trainer disable`.

## Part H: run it again

Submit the same job again. The upload step prints `uploading 1 of 62 blobs`: the shards
are already on the server, only the job record is new.

Change `inner_steps` or `rounds` in `examples/mnist/job.yaml` and submit again to compare
the two runs on the **Jobs** page.

## Problems and solutions

| Problem | Cause | Solution |
|---|---|---|
| `plasmon: command not found` after the install | The install directory is not on the PATH yet | Open a new terminal window. The installer prints the PATH line to add if needed. |
| `Program 'powershell.exe' failed to run: Access is denied` | A second PowerShell was started from inside PowerShell, often in an elevated window | Run the `irm ... | iex` line directly, in a normal PowerShell window. |
| The job stays at `waiting` and the machine shows `idle` | Nobody qualifies for the round | Open the job page or run `plasmon job status <id>`: the `waiting:` line says why, for example `1 idle machine does not meet the job requirements: device cuda`. Check that the trainer logged in to the same server address that the dashboard shows. |
| `the plasmon Python package was not found` | The engine is not installed for the Python the CLI found | Run the `pip install` line again. Set `PLASMON_PYTHON` to the right interpreter if you have several. |
| The browser says "didn't send any data" or `ERR_EMPTY_RESPONSE` on an address like `172.16.30.1` | That address is a VPN tunnel or a virtual machine adapter, not the Wi-Fi | On the Mac use `http://localhost:7117`. From the PC use the `en0` address (`ipconfig getifaddr en0`). With a corporate VPN, the PC may need the VPN off, or the Mac's Wi-Fi address published with `--public-url`. |
| `cannot reach http://192.168.1.20:7117` on the PC | Firewall on the Mac, or a different network | On the Mac, System Settings, Network, Firewall: allow Python. Make sure both computers use the same Wi-Fi. |
| The trainer prints `heartbeat failed: 401` | The machine token was revoked | The trainer re-enrols by itself. If it does not, run `plasmon login` again. |
| The job stays at round 0 | No trainer is idle, or the trainers cannot reach the server | `plasmon fleet`: each machine must show `idle` or `training`. |
| A round shows `expired` for one machine | The machine went offline or exceeded `round_timeout_s` | The round closes with the other machine's update. Nothing to do. |
| `job submit` says `CERTIFICATE_VERIFY_FAILED` | Python from python.org on macOS does not use the system certificates, or a company proxy inspects TLS | Run once `open "/Applications/Python 3.14/Install Certificates.command"` (your version). Behind a company proxy: `export SSL_CERT_FILE=/path/to/company-ca.pem`, or `export PLASMON_INSECURE_DOWNLOADS=1` (the built-in files are checked by MD5), or download the four files with `curl` and submit `examples/mnist/job-local.yaml`. |
| `No module named torch` on Windows | The install did not finish | Run the install command again and read the last lines of the output. |

## Stop

Press `Ctrl+C` in each window. The server keeps all data; the next `plasmon server start`
continues with the same accounts, jobs and ledger.
