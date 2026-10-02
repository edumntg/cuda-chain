# Home lab: a Mac and a Windows PC

This procedure trains an MNIST classifier on two computers at home. The Mac runs the
coordinator and one trainer. The Windows PC runs a second trainer. You submit the job from
the Mac and watch it on both.

The same steps work with the roles reversed. For more computers or other systems, see
[LOCAL-NETWORK.md](LOCAL-NETWORK.md) and the scripts in `examples/local-network/`.

## Before you start

- Both computers are on the same local network.
- Python 3.11 or newer is installed on both.
  - Mac: `brew install python@3.12` or the installer from python.org.
  - Windows: the installer from python.org. Select **Add python.exe to PATH**.
- You know the IP address of the Mac. Find it in System Settings, Network, or with
  `ipconfig getifaddr en0` in Terminal. The examples use `192.168.1.20`.
- No GPU is required. The job trains on CPU in a few minutes. A Mac with Apple Silicon
  uses the GPU through Metal automatically.

## Part A: the Mac (server and first trainer)

### A1. Install the engine

```bash
python3 -m pip install "plasmon[engine] @ git+https://github.com/edumntg/plasmon.git"
python3 -m plasmon --version
```

### A2. Start the coordinator

```bash
python3 -m plasmon server init --org home
python3 -m plasmon server start
```

The server prints:

```
plasmon coordinator
  dashboard  http://192.168.1.20:7117
  api        http://192.168.1.20:7117/api/docs
  data       /Users/you/Library/Application Support/plasmon/server
```

Keep this terminal open.

If macOS asks "Do you want the application to accept incoming network connections?",
select **Allow**.

### A3. Create the owner account

Open `http://192.168.1.20:7117` in a browser. Select **Create account**. The first account
becomes the owner.

### A4. Log in from Terminal and start the first trainer

Open a second Terminal window:

```bash
python3 -m plasmon login --server http://192.168.1.20:7117
python3 -m plasmon trainer start --name mac
```

The login command shows a code and opens the browser. Confirm the code. The trainer then
enrols the Mac and waits for a round. Keep this window open.

## Part B: the Windows PC (second trainer)

### B1. Install the engine

Open PowerShell:

```powershell
py -m pip install "plasmon[engine] @ git+https://github.com/edumntg/plasmon.git"
py -m plasmon --version
```

If `git` is not installed, install it from https://git-scm.com first, or use the zip:

```powershell
py -m pip install "https://github.com/edumntg/plasmon/archive/refs/heads/main.zip#egg=plasmon[engine]"
```

### B2. Log in and start the trainer

```powershell
py -m plasmon login --server http://192.168.1.20:7117
py -m plasmon trainer start --name windows
```

Confirm the code in the browser. Log in with the same account you created on the Mac, or
create a second account for this person. The trainer enrols the PC and waits.

If Windows Firewall shows a prompt, select **Allow**. The trainer only opens outgoing
connections; the prompt is for Python itself.

## Part C: submit the job from the Mac

Open a third Terminal window on the Mac:

```bash
git clone https://github.com/edumntg/plasmon.git
cd plasmon
python3 -m plasmon job submit examples/mnist/job.yaml
```

Output:

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

Within a few seconds both trainers print a line like:

```
12:40:03 INFO round 0 of mnist-home: shard 17 (1000 samples)
12:40:06 INFO round 0 done: loss 2.301→0.412, 71,234 bytes up, fetch 0.3s train 2.1s upload 0.2s
```

## Part D: watch

In the third Terminal window:

```bash
python3 -m plasmon job watch job_3f2a9c1e0b7d
```

Each closed round prints one line. Twenty rounds take two to four minutes on two CPUs.

In the browser:

- **Jobs**, then the job: the loss and accuracy chart, the rounds table and which machine
  trained each round.
- **My machine**: the status of the Mac or the PC, CPU and RAM use, rounds served, and the
  trainer log.
- **Fleet** (owner or operator): both machines side by side.
- **Ledger**: one signed entry per round. Select **Ledger** and read "chain verified".

In a terminal, `python3 -m plasmon fleet` prints the same table as the Fleet page.

## Part E: download and test the model

On the Mac:

```bash
python3 -m plasmon job download job_3f2a9c1e0b7d -o mnist.safetensors
python3 examples/mnist/eval.py mnist.safetensors
```

Expected output after twenty rounds: an accuracy between 96 % and 98 % on the 10,000 test
images.

## Part F: run the trainers at login (optional)

On each computer, replace the `trainer start` window with a service that starts at login:

```bash
python3 -m plasmon trainer enable --name mac           # Mac: launchd agent
```

```powershell
py -m plasmon trainer enable --name windows             # Windows: scheduled task
```

Add `--hours "daily 22:00-07:00"` to train only at night. Remove the service with
`trainer disable`.

## Part G: run it again

Submit the same job again. The upload step prints `uploading 1 of 62 blobs`: the shards
are already on the server, only the job record is new.

Change `inner_steps` or `rounds` in `examples/mnist/job.yaml` and submit again to compare.

## Problems and solutions

| Problem | Cause | Solution |
|---|---|---|
| `cannot reach http://192.168.1.20:7117` on the PC | Firewall on the Mac, or a different network | On the Mac, System Settings, Network, Firewall: allow Python. Make sure both computers use the same Wi-Fi. |
| The trainer prints `heartbeat failed: 401` | The machine token was revoked | The trainer re-enrols by itself. If it does not, run `plasmon login` again. |
| The job stays at round 0 | No trainer is idle, or the trainers cannot reach the server | Check **Fleet** on the dashboard. Each machine must show `idle` or `training`. |
| A round shows `expired` for one machine | The machine went offline or exceeded `round_timeout_s` | The round closes with the other machine's update. Nothing to do. |
| `No module named torch` on Windows | The install did not finish | Run the install command again and read the last lines of the output. |

## Stop

Press `Ctrl+C` in each terminal window. The server keeps all data; the next `server start`
continues with the same accounts, jobs and ledger.
