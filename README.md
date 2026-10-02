# cuda-chain

**A permissionless network for training machine-learning models on other people's GPUs.**
Anyone submits a model and a dataset. Volunteer *trainers* each train on a slice of the
data, their updates are merged, and they are paid in proportion to the training progress
they verifiably contributed.

> **Status: design stage.** This document is the specification: what the network is,
> how a training round works, what it is built on, and how it goes live. Implementation
> starts with milestone M0 (§11). Nothing below is implemented yet unless marked.

---

## Table of contents

1. [The idea](#1-the-idea)
2. [Design principles](#2-design-principles)
3. [How it works](#3-how-it-works)
4. [Architecture](#4-architecture)
5. [Interfaces: CLI and web dashboard](#5-interfaces-cli-and-web-dashboard)
6. [Tech stack](#6-tech-stack)
7. [Is it a server or a blockchain?](#7-is-it-a-server-or-a-blockchain)
8. [Going live: from laptop to first users](#8-going-live-from-laptop-to-first-users)
9. [Prior art and competitors](#9-prior-art-and-competitors)
10. [Repository layout](#10-repository-layout)
11. [Roadmap](#11-roadmap)
12. [Contributing and license](#12-contributing-and-license)

---

## 1. The idea

There are three kinds of participants:

| Role | What they bring | What they get |
|---|---|---|
| **Requester** | A model definition, a dataset, a training recipe and a budget | A trained model, cheaper than renting a cluster |
| **Trainer** | An idle GPU (RTX 3060 and up), bandwidth, uptime | Credits proportional to *verified* training progress |
| **Validator** | A GPU plus stake or reputation | A fee for scoring trainers' work honestly |

A requester publishes a *job*. The network splits the dataset into shards, assigns shards
to trainers, and runs the job in **rounds**. In each round every trainer trains locally
for a few hundred steps on its own shard, then publishes a compressed *update*. Validators
score the updates, the scored updates are merged into a new global model, and the next
round starts. When the budget or the token count is exhausted the requester downloads the
final weights. Trainers are paid per round from the requester's deposit, weighted by their
verified contribution.

Everything is operated from two surfaces: a **CLI** (`cudachain`) that trainers and
requesters live in, and a **web dashboard** where accounts, credits and history live and
where anyone can watch the network run (§5).

The goal is **not** to out-train hyperscalers. It is to make the long tail of training
work (fine-tunes, domain models, 100 M to 10 B parameter pre-training, RL post-training)
cheap and open by using hardware that is already switched on and idle.

## 2. Design principles

Three decisions shape everything else. Each one follows from what has and has not worked
in internet-scale training over the last three years (§9).

**Merging is DiLoCo, not step-wise all-reduce and not weight averaging.** Multi-GPU
training in a datacentre exchanges gradients *every step* over 400 Gbit/s links; over the
internet a per-step all-reduce of even a 150 M parameter model is impossible. Averaging
independently trained weights after many steps does not work either: the replicas drift
apart and the average is worse than any of them. The method every working decentralized
run uses is **DiLoCo** (Distributed Low-Communication training): each trainer runs an
inner optimizer (AdamW) for H ≈ 100–500 local steps, computes a *pseudo-gradient*
Δ = θ_start − θ_end, compresses it, and a single **outer optimizer** (Nesterov momentum)
applies the average of all pseudo-gradients to the global model. Communication drops by
100–500× and convergence matches data-parallel training within a few percent. With
pseudo-gradient compression (DeMo / SparseLoCo: top-k 1–3 % plus 2-bit quantization with
error feedback) the per-round traffic for a 1 B model is tens of megabytes. This is the
base algorithm of cuda-chain.

**A coordinator, not a bespoke blockchain.** Every live decentralized training network
(Templar, Psyche, IOTA, Prime Intellect, Pluralis) has a *logically central* coordinator,
whether a smart contract, a validator set or an orchestrator service, that owns
membership, data assignment and round transitions, with *physically decentralized*
workers doing the compute and a P2P or object-storage layer moving blobs. Payments settle
on an existing chain. Nobody runs a bespoke blockchain for coordination and nobody does a
fully peer-to-peer all-reduce in production. cuda-chain has the same shape (§4, §7), and
spends its engineering on the training, verification and incentive layers rather than on
a transport protocol.

**Verification is built in and public.** If trainers are paid per update, someone will
submit random tensors, copy a neighbour's update, or train on an easier dataset.
Cryptographic proof-of-learning has been broken; bitwise-deterministic re-execution needs
special kernels and doubles the cost. The approach that works in production is
**economic/statistical verification**: validators measure how much each update actually
lowers the loss on held-out data, compare the trainer's *assigned* shard against *random*
data to catch copiers, and re-execute a random sample of rounds with a tolerance. Scores
and scoring code are public, so anyone can recompute them (§3.5).

## 3. How it works

### 3.1 Job specification

A requester submits a `job.yaml` (or the equivalent through the CLI / API):

```yaml
name: tinyllama-es-150m
model:
  source: hf://cudachain/tinyllama-150m-init   # or a safetensors upload; content-addressed
  framework: pytorch
  arch: llama                                   # from an allow-list in v0 (see sandboxing)
  params: 150M
dataset:
  source: hf://HuggingFaceFW/fineweb-edu         # or s3:// or an upload; converted to WebDataset shards
  tokenizer: hf://cudachain/tinyllama-150m-init
  total_tokens: 3_000_000_000
  shard_size_tokens: 50_000_000
recipe:
  algorithm: diloco
  inner_steps: 300
  inner_optimizer: {name: adamw, lr: 4e-4, betas: [0.9, 0.95], weight_decay: 0.1}
  outer_optimizer: {name: nesterov, lr: 0.7, momentum: 0.9}
  compression: {name: sparseloco, topk: 0.02, bits: 2, error_feedback: true}
  per_trainer_batch_tokens: 262_144
  mixed_precision: bf16
requirements:
  min_vram_gb: 12
  min_upload_mbps: 20
  min_trainers: 8
  max_trainers: 64
budget:
  max_credits: 5000
  price_per_verified_token: 1.0e-6
  deadline: 2026-11-15T00:00:00Z
```

The coordinator validates the spec, computes a content hash of model and dataset, converts
the dataset into fixed-size shards stored in object storage, and opens the job for
enrolment when the deposit is locked.

### 3.2 Node identity and enrolment

Every node (trainer, validator, requester, coordinator) has an **Ed25519 keypair**. Its
node ID is the public key. Every message on the network is signed; every blob is
content-addressed by BLAKE3 hash. Trainers announce their hardware (GPU model, VRAM,
measured upload bandwidth, a short benchmark score) and are admitted to a job if they
meet its requirements. In the paid phases a trainer bonds a small stake that can be
slashed for provably bad behaviour (invalid tensor shapes, missed commits after accepting
a slot).

### 3.3 The training round

A job runs in numbered rounds (windows). Each round is roughly `inner_steps × step_time`
long: a few minutes on a consumer GPU.

```
          ┌──────────────── round r ────────────────┐
trainer   pull θ_r ─▶ train H steps on shard(seed,r,id) ─▶ Δ_i = θ_r − θ_i ─▶ compress ─▶ commit hash ─▶ reveal blob
validator                                   ─▶ fetch sampled Δ_i ─▶ score ─▶ publish scores (signed)
coordinator                                                          ─▶ select top-G ─▶ θ_{r+1} = θ_r − η·OuterOpt(mean Δ) ─▶ publish θ_{r+1}
```

1. **Pull.** Trainer fetches the global weights θ_r (only the *changed* parameters since the
   last round it saw; full checkpoint on first join).
2. **Data assignment.** The shard for trainer *i* in round *r* is
   `shard = H(job_seed ‖ r ‖ node_id) mod num_shards`. It is deterministic and public, so
   validators can re-derive it, but a trainer cannot choose an easy shard.
3. **Local training.** H inner steps with AdamW under bf16 autocast. Trainers log loss per
   step; the log is part of the submission.
4. **Pseudo-gradient and compression.** Δ_i is sparsified (top-k with error-feedback
   residual kept locally) and quantized. For a 150 M model at 2 % top-k and 2 bits this is
   ≈ 1–2 MB; for 1 B ≈ 10–20 MB; for 7 B ≈ 70–150 MB per round.
5. **Commit–reveal.** Trainer first publishes `H(Δ_i)` to the coordinator, then uploads the
   blob. This stops a trainer from waiting to see others' updates and copying them.
6. **Scoring (§3.5).** Validators score a sample of updates.
7. **Aggregation.** The coordinator (or, from Phase 3, each validator redundantly) takes the
   top-G scored updates, de-quantizes, averages, applies the outer optimizer, and publishes
   θ_{r+1} plus the round's score table, all signed.
8. **Settlement.** Credits for round *r* are split among the top-G trainers proportional to
   `score_i × tokens_i`. Late or malformed submissions earn nothing for that round.

Trainers may join or leave at round boundaries. A round closes when `min_trainers`
updates are in or a timeout fires; stragglers' updates for round *r* arriving during
round *r+1* are either discarded or applied with staleness correction (HeLoCo-style),
configurable per job.

### 3.4 Communication budget

Why this is feasible on home connections (upload is the constraint):

| Model | Dense Δ (fp32) | Compressed Δ (2 % top-k, 2-bit + indices) | Round length on RTX 4090 (300 steps) | Upload needed |
|---|---|---|---|---|
| 150 M | 600 MB | ≈ 2 MB | ≈ 3 min | < 1 Mbit/s |
| 1 B | 4 GB | ≈ 15 MB | ≈ 12 min | < 1 Mbit/s |
| 7 B (LoRA / partial) | 28 GB (full) / 0.3 GB (LoRA r=64) | ≈ 100 MB / 1 MB | ≈ 25 min | 1–2 Mbit/s |

Downloads of θ_{r+1} are larger (the coordinator can send the dense delta or the
compressed aggregate; the latter is the same order as one update). Pipeline parallelism
for models that do not fit on one GPU is deliberately out of scope until Phase 4 (§11).

### 3.5 Verification and anti-cheating

Validators are nodes with stake or earned reputation. In each round each validator:

- runs a **cheap check on every update**: signature, tensor shapes, quantization ranges,
  timeliness, and a *sync score* (the trainer's declared θ_r hash must match the real one);
- runs an **expensive check on a random sample** (≈ 5 updates per validator per round):
  `gain_assigned = L(θ_r) − L(θ_r − βΔ_i)` on the trainer's *assigned* shard and
  `gain_random = L(θ_r) − L(θ_r − βΔ_i)` on a random held-out shard. An honest update has
  `gain_assigned > gain_random > 0`. A copied update has `gain_assigned ≈ gain_random`. A
  random update has both ≈ 0 or negative. The running mean of the sign of
  `(gain_assigned − gain_random)` is the trainer's **honesty score**; its magnitude feeds
  an OpenSkill rating that determines selection into the top-G and payout weight;
- optionally **re-executes** a sampled trainer's round with the same seed and compares the
  compressed update by Jaccard/cosine similarity within a calibrated tolerance (bitwise
  equality is not possible across GPUs).

Validator scores are published and signed; the coordinator uses the stake-weighted median.
A validator whose scores are consistently outliers loses reputation. All scoring code is
open source and all score tables are public, so anyone can recompute them. This is a
direct answer to the "black-box validator" critique of Bittensor.

What this does **not** solve, stated plainly: one bad update can land in the aggregate
before its author is down-weighted (mitigated by top-G selection and by clipping each Δ to
a norm bound); collusion between a majority of validators; and a trainer who honestly trains
on *wrong* data cannot be distinguished from a slightly weak GPU. These are the open
problems of the whole field (§9).

### 3.6 Rewards and economics

- Unit of account: **credits**, 1 credit = 1 USD-cent equivalent. Requesters buy credits
  (card / USDC); trainers withdraw credits (USDC, or fiat payout in later phases).
- Per round, the job pays `price_per_verified_token × Σ tokens_i` for the top-G trainers,
  split by `score_i × tokens_i`. A 5–10 % protocol fee funds validators and infrastructure.
- Phase 1 and 2 ledger: an **append-only, hash-chained, signed log** published by the
  coordinator (each entry references the previous entry's hash; anyone can audit; the
  coordinator cannot rewrite history without detection). This is "blockchain-shaped"
  without a consensus network.
- Phase 3: settlement contract on an existing L2 (Base) or Solana: deposits, per-job escrow,
  payouts by Merkle proof of the round score table, slashing of trainer and validator bonds.
  **No new chain, no new token in v1.** A governance/utility token is a Phase 4 question,
  only if there is something a token does that credits cannot.

### 3.7 Sandboxing and safety

Trainers execute code chosen by requesters. In **v0 there is no arbitrary code**: the model
must be one of an allow-listed set of architectures instantiated from a config (Llama,
GPT-2, Mistral, ResNet, ViT, plus LoRA adapters on allow-listed HF checkpoints), and data
loaders are built-in (WebDataset shards of tokenized text or images). This removes remote
code execution from the threat model entirely. From Phase 3, custom `nn.Module` code runs
inside a container with no network access, a read-only filesystem, and GPU-only
capabilities (Docker with `--gpus`, seccomp profile, later gVisor), and is signed by the
requester.

Dataset privacy: shards are visible to every trainer that gets them. cuda-chain v1 is for
**public or licensable data only**; private-data training is a federated-learning problem
(see Flower in §9) and is out of scope.

## 4. Architecture

```
   ┌─────────────────────┐          ┌─────────────────────┐
   │  CLI / TUI          │          │  Web dashboard      │
   │  cudachain login    │          │  sign-up · plans    │
   │  job · trainer ·    │          │  credits · history  │
   │  validator · net    │          │  live network view  │
   └──────────┬──────────┘          └──────────┬──────────┘
              │  signed API calls (HTTPS / gRPC) │  HTTPS + SSE
              ▼                                  ▼
                         ┌──────────────────────────────────────────────┐
                         │               Coordinator (API)              │
                         │  accounts · jobs · rounds · assignment       │◀──── validator agents
                         │  aggregation · score tables · ledger         │      (score, re-execute)
                         │  FastAPI · Postgres · Redis · Python workers │
                         └───────┬───────────────────────────┬──────────┘
                                 │ signed metadata (gRPC/HTTP)│
                                 ▼                           ▼
                   ┌─────────────────────┐        ┌─────────────────────┐
                   │ Blob store          │        │ Settlement          │
                   │ S3-compatible (R2 / │        │ Phase 1–2: ledger   │
                   │ MinIO) + P2P blobs  │        │ Phase 3: contracts  │
                   │ (Iroh / Hivemind)   │        │ on Base or Solana   │
                   └──────────┬──────────┘        └─────────────────────┘
                              │ θ_r, shards, Δ_i (content-addressed, signed)
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
   ┌──────────┐         ┌──────────┐         ┌──────────┐
   │ trainer  │         │ trainer  │   ...   │ trainer  │     `cudachain trainer start`
   │ RTX 3090 │         │ RTX 4070 │         │ A100     │     Python · PyTorch · CUDA
   └──────────┘         └──────────┘         └──────────┘
```

**Components**

| Component | Responsibility | Trust assumption |
|---|---|---|
| `coordinator` | Job registry, round state machine, deterministic data assignment, aggregation, publishing θ_{r+1}, ledger | Phase 1–2: run by the project, fully auditable. Phase 3: stateless replicas behind a multi-validator attestation; aggregation recomputed redundantly by validators |
| `trainer` | Pull weights, train, compress, commit-reveal, upload | Untrusted; verified by validators |
| `validator` | Score updates, re-execute samples, publish signed scores | Semi-trusted via stake/reputation; scores are public and recomputable |
| `blobstore` | Move checkpoints, shards and updates | Dumb storage; everything is hashed and signed, so a malicious store can only deny service |
| `settlement` | Hold deposits, pay out, slash | Phase 1–2: coordinator's ledger. Phase 3: smart contracts |
| `cli` | `cudachain` TUI and subcommands: login, jobs, trainers, validators, credits, network | Client; holds the node keypair and an API token |
| `web` | Dashboard: accounts, plans and credits, job and trainer history, live network view, public leaderboard and explorer | Client of the same API; no privileged access |
| `sdk` | Python package used by the CLI and by scripts (`cudachain.Client`) | Client |

**Why a coordinator and not a DHT for everything.** Membership, round transitions and
assignment need a single source of truth with sub-second latency; a DHT gives neither.
The coordinator holds no secrets that matter (every artefact is signed by its author and
content-addressed) and keeps a public hash-chained log, so it can be replaced or replicated
without trusting its history. Blob *transfer* is where P2P pays off (trainers seeding
θ_{r+1} to each other rather than everyone hitting one bucket), so that is where the P2P
layer goes, in Phase 2.

## 5. Interfaces: CLI and web dashboard

Two front ends, one API. Everything the web app can do, the CLI can do, and vice versa,
except payments, which only happen in the browser. Both talk to the coordinator with the
same signed requests; neither has privileges the other lacks.

### 5.1 The CLI (`cudachain`)

The CLI is where trainers and requesters spend their time, so it has to feel good. The
reference points are the current generation of terminal tools (Claude Code, Gemini CLI,
Codex, `gh`, `boxd`, `pi`): an animated start screen, a real colour theme, live tables and
progress, keyboard-driven panels, and plain text or JSON when piped.

**Start-up.** Running `cudachain` with no arguments in a TTY plays a short ASCII animation
(≈ 1 s, skippable with any key): chain links assembling into the logo with a colour sweep,
followed by a one-screen status: who you are, credits, trainers online, your active jobs,
latest round of each. Animation is off when stdout is not a TTY, when `NO_COLOR` or
`CUDACHAIN_NO_ANIM` is set, or with `--plain`. The frames live in `tui/logo.py` as a list
of strings so they are easy to redraw.

```
  ██████╗██╗   ██╗██████╗  █████╗      ██████╗██╗  ██╗ █████╗ ██╗███╗   ██╗
 ██╔════╝██║   ██║██╔══██╗██╔══██╗    ██╔════╝██║  ██║██╔══██╗██║████╗  ██║
 ██║     ██║   ██║██║  ██║███████║    ██║     ███████║███████║██║██╔██╗ ██║
 ██║     ██║   ██║██║  ██║██╔══██║    ██║     ██╔══██║██╔══██║██║██║╚██╗██║
 ╚██████╗╚██████╔╝██████╔╝██║  ██║    ╚██████╗██║  ██║██║  ██║██║██║ ╚████║
  ╚═════╝ ╚═════╝ ╚═════╝ ╚═╝  ╚═╝     ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝
  ◆ eduardo        ◆ 1,240 credits        ◆ 37 trainers online        ◆ v0.1.0

  JOB                    STATE     ROUND   LOSS     TRAINERS   SPENT
  tinyllama-es-150m      running   412     2.981    19         1,114 cr   ▂▃▃▄▅▅▆▆▇▇
  resnet50-cifar-ft      done      120     0.412    8          210 cr     ▁▂▄▆▇▇▇███

  › Press  j  jobs   t  trainers   n  network   c  credits   ?  help   q  quit
```

**Commands.** Flat verbs grouped by noun; every command accepts `--json` for scripting
and `--plain` for logs.

```
cudachain                         open the TUI home screen
cudachain login | logout | whoami device-code login (prints a code and URL; confirm in the browser)
cudachain init                    create this machine's Ed25519 keypair and link it to your account

cudachain job submit job.yaml     validate, estimate cost, confirm, submit
cudachain job list | status <id> | logs <id> --follow | cancel <id> | download <id> [--round N]

cudachain trainer start [--gpus 0,1] [--job <id> | --any] [--max-hours 8]
cudachain trainer status | stop | earnings

cudachain validator start | status

cudachain net status | peers | rounds <job>
cudachain credits                 balance and recent ledger entries; `credits buy` opens the browser
cudachain ledger verify           re-verify the hash chain and signatures of the public ledger
cudachain dashboard               full-screen TUI (same panels as the home screen, live)
```

**Live views.** `trainer start` renders a live panel: GPU utilisation and temperature,
current round, inner-step progress bar, loss sparkline, bytes uploaded this round, verified
tokens and credits earned this session. `job logs --follow` renders loss per round,
trainers per round and spend. `net status` is a table of jobs and a histogram of GPUs by
model.

**Login flow.** `cudachain login` requests a device code from the coordinator, prints
`https://cudachain.dev/device` plus an 8-character code, and polls. The user confirms in
the browser (creating an account if needed). The CLI stores a scoped API token in the OS
keychain (fallback: `~/.cudachain/credentials` with mode 600). The machine keypair created
by `cudachain init` is registered to the account so earnings from that machine accrue to
the right wallet. Tokens are revocable from the dashboard.

**Why Python for the TUI.** The trainer is Python (PyTorch), and shipping one `pip install
cudachain` that gives both the trainer and the TUI beats shipping a Go or Node binary plus
a Python sidecar. The Python TUI stack is mature enough for this: **Typer** for commands,
**Rich** for colour, tables, progress and the start-up animation (`rich.live`), and
**Textual** for the full-screen dashboard. If a native binary is ever needed (instant
start, no Python on the machine), the API is designed so a Bubble Tea or Ink client can be
added without touching the coordinator.

### 5.2 The web dashboard

The web app is for everything that benefits from a browser: creating an account, paying,
reading history, and watching the network. It is also the public face of the project.

**Public pages (no login)**

- **Network status:** trainers online, GPUs by model, aggregate throughput, active jobs,
  bytes per round, uptime of the coordinator, last ledger entry hash.
- **Job explorer:** every public job with its loss curve, rounds, trainers per round, and
  the score table per round (the verification is public by design, §3.5).
- **Leaderboard:** trainers by verified tokens, honesty score and uptime; validators by
  agreement with the median.
- **Ledger browser:** the hash-chained log, searchable, with a one-click verify.

**Account pages**

- **Sign-up / login:** email + password or magic link, GitHub and Google OAuth, passkeys
  later. The same accounts the CLI logs into.
- **Credits and plans:** buy credits by card (Stripe) or USDC; plans give monthly credits
  at a discount plus perks such as priority scheduling and longer checkpoint retention.
  Invoices and receipts. Trainers see **earnings** here and configure payout (USDC
  address; Stripe Connect for fiat in a later phase).
- **My jobs:** submit through a form that produces the same `job.yaml` the CLI uses, cost
  estimate before confirming, live loss curve, per-round trainers and scores, download
  checkpoints, cancel. History of every job with spend.
- **My trainers:** every linked machine, online state, GPU, last heartbeat, rounds served,
  earnings, honesty score, and a "revoke" button.
- **Account:** API tokens (create, scope, revoke), linked keypairs, notification settings
  (email or webhook when a job finishes or a trainer goes offline).
- **Admin (project staff):** validator operations, job moderation, refunds.

**Real time.** The coordinator publishes round events over Server-Sent Events; the
dashboard and the TUI subscribe to the same stream, so both show a new round within a
second of it closing.

**Plans sketch (to be priced after Phase 1 data)**

| Plan | For | Includes |
|---|---|---|
| Free | Trainers; requesters trying it out | Earn credits; submit jobs up to a small size on the free queue |
| Pay-as-you-go | Most requesters | Buy credits as needed; standard priority |
| Pro (monthly) | Teams running jobs every week | Monthly credit bundle at a discount, priority scheduling, 90-day checkpoint retention, more API tokens |
| Enterprise | Labs | Reserved trainer pools, private datasets (Phase 4), invoicing |

## 6. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Trainer runtime | **Python 3.11+, PyTorch 2.x, CUDA 12.x** (bf16 autocast, `torch.compile` optional) | Where every model and every volunteer already is. CPU and Apple MPS backends supported for small jobs and for developer testing; CUDA is the first-class target |
| Training algorithm | **DiLoCo** inner/outer loop; reference from Prime Intellect's `OpenDiLoCo` / `prime` (Apache-2.0) | Proven at 1–100 B scale over WAN |
| Compression | **SparseLoCo / DeMo** style top-k + low-bit + error feedback; reference code from Templar (MIT) and Nous Psyche (Apache-2.0/MIT) | 100–500× bandwidth reduction, convergence proven |
| Tensor wire format | **safetensors** for checkpoints; custom flat binary frame (BLAKE3 hash, dtype, shape, packed indices + values) for compressed Δ | Zero-copy binary; tensors never travel as text |
| Dataset format | **WebDataset** `.tar` shards of pre-tokenized `uint16`/`uint32` arrays, or images; content-addressed | Streamable, sliceable, cacheable, standard |
| Identity / signing | **Ed25519** (PyNaCl / `cryptography`), **BLAKE3** hashing | Fast, small, standard; same as Iroh node IDs |
| Coordinator API | **FastAPI** + **Pydantic v2** + **SQLAlchemy 2.0** on **PostgreSQL**; **Redis** for round timers and queues; **gRPC** streaming for trainer heartbeats and round events | Python keeps coordinator and trainer in one language; Postgres gives real transactions and row locks for batch assignment |
| Blob storage | **S3-compatible** (Cloudflare R2 in production, MinIO locally); Phase 2: **Iroh** (Rust, QUIC, hole-punching, blobs + gossip) or **Hivemind** DHT for peer seeding | Start boring, add P2P where it reduces cost |
| Validator agent | Same Python package as trainer, `cudachain validator start` | One binary, two modes |
| Scoring | Templar **Gauntlet**-style loss-delta scoring, **OpenSkill** ratings (`openskill` PyPI) | Deployed in production for 72 B; MIT |
| Settlement (Phase 3) | **Solidity on Base** (OpenZeppelin, Foundry) or **Anchor on Solana**; Merkle-root payouts | Use an existing chain; both have public reference implementations in this space |
| Sandbox (Phase 3) | **Docker** with `--gpus`, no network, read-only rootfs, seccomp; **gVisor** when available | Standard GPU isolation story |
| CLI / TUI | **Typer** (commands) + **Rich** (colour, tables, progress, start-up animation) + **Textual** (full-screen dashboard); `pip install cudachain`; token in OS keychain via `keyring` | One install gives trainer and TUI; mature Python stack; `--json`/`--plain` for scripts |
| SDK | `cudachain` Python package, `cudachain.Client` | Shared by CLI and user scripts |
| Web dashboard | **Next.js** (React, TypeScript) + **Tailwind** + **shadcn/ui**; charts with **Recharts**; live updates over **SSE**; deployed on Vercel or beside the coordinator | Standard, fast to build, good charting; the API stays in Python |
| Accounts and auth | Coordinator owns accounts: email + password / magic link, GitHub and Google OAuth (**authlib**), device-code flow for the CLI, scoped API tokens, passkeys later | One identity for CLI and web; no third-party auth lock-in |
| Payments | **Stripe** (cards, subscriptions for plans, Connect for fiat payouts later); **USDC** via Coinbase Commerce in Phase 2, direct on-chain in Phase 3 | Credits are the unit; fiat and crypto are just on-ramps |
| Packaging / ops | `pyproject.toml` (uv/hatch), Docker images for coordinator and trainer, `docker compose` dev stack, GitHub Actions, **pytest** with a two-trainer in-process integration test | Testable from day one |
| Observability | Structured logs (structlog), Prometheus metrics, Grafana dashboard: loss per round, trainers online, bytes per round, score distribution | Trainers need a public leaderboard and requesters need a loss curve |

Deliberately **not** in the stack: a new blockchain, a new P2P protocol, JSON tensors,
C++ (until there is a measured hot path that PyTorch does not cover), raw CUDA kernels in
v1. The name refers to the hardware the network runs on and to the hash-chained ledger;
users never write kernels.

## 7. Is it a server or a blockchain?

Both questions people ask, answered directly.

**Is there a server?** Yes. There is a coordinator service and it is the only way the
system can start simply and ship. In Phase 1–2 it is one deployment run by the project. It
is, however, *designed to be untrusted*: every artefact it relays is signed by its author
and content-addressed; its ledger is hash-chained and public; its aggregation can be
recomputed by any validator from public inputs. If it misbehaves, that is detectable; if it
dies, a replica can resume from the public log and the blob store. From Phase 3, several
validators each run a coordinator replica and sign the round result; the client accepts a
round only when a quorum agrees. That is a small permissioned BFT set, not a public chain.

**Is it a blockchain?** Not in the sense of a new consensus network with its own token.
The *chain* in cuda-chain refers to (a) the hash-chained ledger of rounds, scores and
payouts, and (b) settlement of value on an existing public chain once there is value to
settle. This is the same shape as Psyche (coordinator = Solana program), Templar
(coordinator = validator set + Bittensor for emissions) and Prime Intellect (Rust
orchestrator + contracts on Base). Running a bespoke L1 has consumed several well-funded
teams and delivered no training; this project will not repeat that.

**Is it decentralized?** Compute, yes, from day one: the GPUs are other people's. Trust,
progressively: Phase 1 trusts the project's coordinator (while making its behaviour
auditable); Phase 3 trusts a quorum of staked validators; the design never requires
trusting trainers.

## 8. Going live: from laptop to first users

### Phase 0: it works on one machine (target: 6–8 weeks of work)

- `docker compose up` starts Postgres, Redis, MinIO, one coordinator and two trainers
  (CPU, or CUDA if present).
- Reference job: a 10–30 M parameter GPT-2 on TinyStories or Shakespeare, DiLoCo with
  H=50, 2 % top-k. **Acceptance test:** final loss within 5 % of the same model trained
  on one GPU with the same token budget, with network traffic measured and reported.
- Everything in §3.1–3.4 implemented; scoring (§3.5) stubbed to "all honest".
- Integration test suite: 2 trainers join mid-run, 1 leaves, 1 submits garbage.

Trainer hardware for the dev loop: any machine; GPU optional.

### Phase 1: closed alpha, one shared run (target: first 10–50 trainers)

Launch the way Pluralis (Node0), Nous (Psyche) and Macrocosmos (Train-at-Home) all did:
**not with a marketplace but with one public reference model everyone trains together.**
That gives early trainers a shared goal, gives the team one run to debug, and produces
an artefact (open weights) that proves the network works.

- **Infrastructure:** coordinator on one VPS (e.g. Hetzner AX or a 2-vCPU cloud box; the
  coordinator does aggregation of ≤ 1 B params, which fits a 16 GB CPU box or a small GPU
  instance), Postgres managed or on the box, Cloudflare R2 for blobs (free egress matters:
  every trainer pulls θ_{r+1} every round). Estimated cost < 100 USD/month at this scale.
- **Reference run:** a 150 M Llama-style model on 3–5 B tokens of FineWeb-Edu, DiLoCo
  H=300, bf16, 2 % top-k 2-bit. On 20 consumer GPUs this takes about one to two weeks.
  Publish loss curve and leaderboard live.
- **Trainer onboarding:** sign up on the dashboard, then `pip install cudachain && cudachain login && cudachain trainer start --join <run>`
  or `docker run cudachain/trainer`. Minimum: NVIDIA GPU with ≥ 8 GB VRAM (RTX 3060 /
  3070 / 4060 Ti and up), Linux or WSL2, 20 Mbit/s upload, driver ≥ 535. Invite codes via
  Discord/GitHub; 10–50 people.
- **Verification:** validators run by the project only (2–3 GPUs), full Gauntlet scoring
  live, scores public. Credits accrue in the hash-chained ledger; not yet withdrawable.
  The public leaderboard, the live job page and a "verified tokens trained" badge are
  the reward. The dashboard ships in this phase with network status, job explorer,
  leaderboard and the account pages; payments come in Phase 2.
- **Exit criterion:** the 150 M model reaches the loss of a single-GPU baseline within
  5–10 %; at least one cheating attempt (seeded by the team) is caught and down-weighted;
  no round lost to coordinator failure.

### Phase 2: open alpha, paid jobs (target: first 3–5 external requesters)

- **Job submission opens** for allow-listed architectures and public datasets; requesters
  pay in credits bought by card (Stripe) or USDC. Fine-tunes and LoRA jobs on 1–7 B
  checkpoints are the first paid product because they are small, fast, and the market
  already exists (compare Gradients on Bittensor).
- Trainers can **withdraw** credits (USDC on Base; fiat later). Protocol fee 10 %.
- **P2P blob seeding** (Iroh or Hivemind) so trainers serve θ_{r+1} to each other and the
  bucket bill does not scale with trainer count.
- Validator set opens to **staked community validators** (bond in USDC); scores
  stake-weighted-median; validator slashing for outlier scoring.
- Public **status page and job explorer** (loss per round, trainers, bytes, scores).
- Target: 100–500 trainers, a handful of paying jobs, and the economics measured honestly
  (credits paid per verified token vs. the equivalent cloud GPU hour).

### Phase 3: decentralized trust

- Settlement contracts on Base (or Solana): escrow per job, Merkle payouts per round,
  trainer and validator bonds, slashing.
- Coordinator replicated across validators; round results accepted on quorum signature.
- Custom model code in sandboxed containers; RL post-training jobs with TOPLOC-style
  rollout verification (the cheapest verifiable workload, see Prime Intellect in §9).

### Phase 4: scale

- Pipeline parallelism for models that do not fit one GPU (SWARM / IOTA / Pluralis style),
  which also changes the accounting (per-stage credit).
- Asynchronous rounds with staleness correction (HeLoCo / Decoupled DiLoCo).
- Governance of parameters and fees; token only if it is needed for something credits
  cannot do.

## 9. Prior art and competitors

Full research notes with sources are in [`docs/LANDSCAPE.md`](docs/LANDSCAPE.md). Summary
as of October 2026:

| Project | Model of coordination | Training method | Verification | Rewards | Status / scale | Open source |
|---|---|---|---|---|---|---|
| **Templar / Covenant AI** (was Bittensor SN3) | Validator set + cloud buckets; miners get deterministic shards | DiLoCo + DeMo → SparseLoCo | Gauntlet: loss-delta on assigned vs random data, OpenSkill | TAO emissions ∝ score | Covenant-72B (72.7 B, 1.1 T tokens, 70+ nodes, Mar 2026). Covenant left Bittensor Apr 2026 | Yes, MIT, Python |
| **Nous Research Psyche** | Coordinator is a **Solana program**; P2P over Iroh | DisTrO/DeMo | Witnesses + statistical similarity of recomputed updates | None yet (contribution-driven) | Consilience 40 B, Hermes 4.3 36 B trained end-to-end on Psyche | Yes, Rust, Apache/MIT |
| **Prime Intellect** | Rust orchestrator + contracts on Base; now mostly a compute marketplace + RL stack | OpenDiLoCo (on Hivemind); prime-rl async RL; SHARDCAST | TOPLOC for inference rollouts | Testnet payouts | INTELLECT-1 10 B, INTELLECT-2 32 B (decentralized RL). INTELLECT-3 trained centrally. $130 M at $1 B (Jul 2026); protocol repo archived | Yes, Python/Rust |
| **Macrocosmos IOTA** (Bittensor SN9) | Central orchestrator; pipeline-parallel stages | SWARM-style PP, Butterfly all-reduce, activation compression | CLASP Shapley-style credit; recompute samples | TAO | Orion-100B PoC, Orion-16B live on ~180 GPUs; "Train at Home" Mac app | Yes, Python |
| **Pluralis Research** | Hivemind-based; model-parallel so no node holds full weights | Protocol Models (compressed activations) | Research | Reputation only | Node0-7.5 B (1,642 GPUs, 198 cities); Pluralis-8B 500 B tokens at 63 % of H100-cluster efficiency | Yes, Python |
| **Gensyn** | Ethereum L2 rollup; RL Swarm | Verde refereed delegation, RepOps | Deterministic re-execution with bisection | $AI token (Apr 2026) | Testnet since Mar 2025, RL Swarm paused Jan 2026; training mainnet not live; Open-1B is *auditable* centralized training | Partly |
| **Hivemind / Petals / SWARM** | Library: libp2p DHT, decentralized averaging | Any | None | None | Hivemind 1.1.12 (Jan 2026) maintained; Petals swarm mostly idle | Yes, MIT |
| **Flower / FedML** | Federated learning frameworks (data stays with owner) | FedAvg family; Photon for LLMs | Honest-but-curious | None | Flower dominant FL framework; FedML pivoted to TensorOpera cloud | Yes |
| **Akash, io.net, Render, Golem, Vast.ai, Salad** | GPU *rental* marketplaces | None (you bring your own orchestration) | n/a | Token or fiat per GPU-hour | Large (io.net ~370 k GPUs claimed) | Varies |
| **Together AI, Exo** | Together: started from decentralized-training research, now a centralized neocloud ($8.3 B). Exo: LAN clusters for inference | | | | | |

**What this tells cuda-chain**

1. The algorithmic stack is settled and open: DiLoCo + sparse/low-bit pseudo-gradients. Use
   the reference implementations, do not reinvent.
2. The architecture is settled: logically central coordinator, decentralized workers,
   settlement on an existing chain. Nobody who tried "fully P2P" or "own L1" shipped
   training.
3. Every live network trains **its own** model. A **permissionless job market** where third
   parties submit model + dataset exists only as fine-tuning competitions (Gradients). That
   is the open space and the differentiator, together with transparent, recomputable
   scoring (the exact thing the Covenant/Bittensor split was about).
4. Economics are unproven at the frontier: the best-funded teams train flagships on
   InfiniBand clusters. cuda-chain targets the long tail (fine-tunes, ≤ 10 B pre-training,
   RL rollouts), where volunteer compute is already competitive.
5. Verification is the hard, unsolved problem. Ship statistical verification and publish
   detection rates rather than promising cryptographic proofs.

## 10. Repository layout

One Python monorepo plus the web app:

```
cudachain/
├── pyproject.toml
├── docker-compose.yml            # postgres, redis, minio, coordinator, 2× trainer
├── src/cudachain/
│   ├── cli/                      # typer: login | job | trainer | validator | net | credits | ledger
│   ├── tui/                      # rich + textual: logo animation, home screen, live panels, dashboard
│   ├── proto/                    # signed message schemas (pydantic) + gRPC defs
│   ├── crypto/                   # ed25519 identity, blake3 content addressing
│   ├── blobs/                    # s3 client, content-addressed cache, (phase 2) iroh/hivemind
│   ├── data/                     # webdataset sharding, deterministic assignment
│   ├── train/                    # diloco inner/outer loop, compression (sparseloco/demo), frames
│   ├── trainer/                  # agent: enrol, pull, train, commit-reveal, upload
│   ├── validator/                # agent: cheap checks, gauntlet scoring, re-execution
│   ├── coordinator/              # fastapi app, round state machine, aggregation, ledger
│   └── models/                   # allow-listed architectures (llama, gpt2, resnet, lora)
├── web/                          # next.js dashboard: public pages, account, credits, jobs, trainers
├── contracts/                    # phase 3: foundry project (escrow, payouts, bonds)
├── tests/                        # unit + two-trainer integration test
└── docs/
    ├── LANDSCAPE.md              # competitor and research notes with sources
    └── PROTOCOL.md               # (to write) message formats and round state machine
```

## 11. Roadmap

- [ ] **M0 Scaffold.** `pyproject`, identity, signed messages, blob client, compose stack, CI.
      CLI skeleton with the start-up animation, `login` (device code), `whoami`, `--json`.
- [ ] **M1 DiLoCo locally.** Inner/outer loop, SparseLoCo compression, binary Δ frames,
      two in-process trainers reach single-GPU loss on a 10–30 M model. Traffic measured.
- [ ] **M2 Coordinator.** Job spec, round state machine, deterministic assignment,
      commit-reveal, aggregation, hash-chained ledger, join/leave mid-run. Accounts and
      API tokens. CLI `job`, `trainer`, `net` commands with live Rich panels.
- [ ] **M3 Verification.** Gauntlet scoring, OpenSkill ratings, top-G selection, seeded
      cheating tests (random Δ, copied Δ, wrong shard) all detected.
- [ ] **M4 Alpha run.** VPS + R2, 150 M reference model, 10–50 invited trainers. Web
      dashboard v1: sign-up, network status, job explorer, leaderboard, my trainers.
      Textual full-screen TUI. (Phase 1 above.)
- [ ] **M5 Paid jobs.** Credits and plans in the dashboard (Stripe, USDC in; USDC out),
      job submission form, history and invoices, allow-listed fine-tune/LoRA jobs,
      community validators with bonds, P2P seeding. (Phase 2.)
- [ ] **M6 Contracts and quorum coordinator.** (Phase 3.)
- [ ] **M7 Pipeline parallelism, async rounds, custom code sandbox.** (Phase 4.)

## 12. Contributing and license

Work happens on `main` under the layout in §10, starting with M0. Issues are welcome,
especially from people with a consumer GPU who want to be alpha trainers, and from anyone
who has run DiLoCo, Hivemind, Psyche or Templar nodes.

License: to be decided before M4; the intended choice is **Apache-2.0** for the client and
coordinator (matching the ecosystem it builds on) with scoring code required to stay open.
