# cuda-chain

**A permissionless network for training machine-learning models on other people's GPUs.**
Anyone submits a model and a dataset. Volunteer *trainers* each train on a slice of the
data, their updates are merged, and they are paid in proportion to the training progress
they verifiably contributed.

> **Status: design stage.** The three code branches in this repository (`development`,
> `initial-docs`, `jules_wip_*`) are early experiments. None of them trains a model, and
> two of them do not build or start. See [`docs/AUDIT.md`](docs/AUDIT.md) for the
> line-by-line audit. This README is the redesign: what the system should be, how it
> works, what it is built on, and how it goes live. Nothing below is implemented yet
> unless explicitly marked.

---

## Table of contents

1. [The idea](#1-the-idea)
2. [What changed from the original idea, and why](#2-what-changed-from-the-original-idea-and-why)
3. [How it works](#3-how-it-works)
4. [Architecture](#4-architecture)
5. [Tech stack](#5-tech-stack)
6. [Is it a server or a blockchain?](#6-is-it-a-server-or-a-blockchain)
7. [Going live: from laptop to first users](#7-going-live-from-laptop-to-first-users)
8. [Prior art and competitors](#8-prior-art-and-competitors)
9. [Repository layout](#9-repository-layout)
10. [Roadmap](#10-roadmap)
11. [Audit of the existing code](#11-audit-of-the-existing-code)
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

The goal is **not** to out-train hyperscalers. It is to make the long tail of training
work (fine-tunes, domain models, 100 M to 10 B parameter pre-training, RL post-training)
cheap and open by using hardware that is already switched on and idle.

## 2. What changed from the original idea, and why

The original pitch was: "each trainer trains one batch, then combine the weights, like
multi-GPU training". Two parts of that do not survive contact with the literature or the
code, and one part was missing.

**"Combine the weights" has to be a specific algorithm.** Multi-GPU training works because
GPUs exchange gradients *every step* over 400 Gbit/s links. Over the internet a step-wise
all-reduce of even a 150 M parameter model is impossible. Averaging independently trained
weights after many steps does not work either; the replicas drift apart and the average is
worse than any of them. The method every working decentralized run uses today is
**DiLoCo** (Distributed Low-Communication training): each worker runs an inner optimizer
(AdamW) for H ≈ 100–500 local steps, computes a *pseudo-gradient* Δ = θ_start − θ_end,
compresses it, and a single **outer optimizer** (Nesterov momentum) applies the average of
all pseudo-gradients to the global model. Communication drops by 100–500× and convergence
matches data-parallel training within a few percent. Combined with pseudo-gradient
compression (DeMo / SparseLoCo: top-k 1–3 % plus 2-bit quantization with error feedback)
the per-round traffic for a 1 B model is tens of megabytes. This is now the base
algorithm of cuda-chain, not an implementation detail.

**"P2P like a blockchain" is not how any successful network is built.** Every live
decentralized training network (Templar, Psyche, IOTA, Prime Intellect, Pluralis) has a
*logically central* coordinator (a smart contract, a validator set, or an orchestrator
service) that owns membership, data assignment and round transitions, with *physically
decentralized* workers doing the compute and a P2P or object-storage layer moving blobs.
Payments settle on an existing chain. Nobody runs a bespoke blockchain for coordination
and nobody does a fully peer-to-peer all-reduce in production. cuda-chain follows the same
shape (§4, §6). The three existing branches each rewrote a transport layer from scratch and
never reached the training step; that is the trap this design avoids.

**Verification was missing entirely.** If trainers are paid per update, someone will
submit random tensors, copy a neighbour's update, or train on an easier dataset.
Cryptographic proof-of-learning has been broken; bitwise-deterministic re-execution needs
special kernels and doubles the cost. The approach that works in production is
**economic/statistical verification**: validators measure how much each update actually
lowers the loss on held-out data, compare the trainer's *assigned* shard against *random*
data to catch copiers, and re-execute a random sample of rounds with a tolerance. This is
the Gauntlet mechanism from Templar (MIT-licensed) and the Psyche witness scheme; cuda-chain
adopts it (§3.5).

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
for models that do not fit on one GPU is deliberately out of scope until Phase 4 (§10).

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
problems of the whole field (§8).

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
(see Flower in §8) and is out of scope.

## 4. Architecture

```
                         ┌──────────────────────────────────────────────┐
                         │               Coordinator (API)              │
  requester CLI ────────▶│  jobs · rounds · assignment · aggregation    │◀──── validator agents
  (submit, pay, fetch)   │  score tables · hash-chained ledger          │      (score, re-execute)
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
| `cli` / `sdk` | `cudachain job submit`, `cudachain trainer start`, Python SDK | Client |

**Why a coordinator and not a DHT for everything.** Membership, round transitions and
assignment need a single source of truth with sub-second latency; a DHT gives neither.
The coordinator holds no secrets that matter (every artefact is signed by its author and
content-addressed) and keeps a public hash-chained log, so it can be replaced or replicated
without trusting its history. Blob *transfer* is where P2P pays off (trainers seeding
θ_{r+1} to each other rather than everyone hitting one bucket), so that is where the P2P
layer goes, in Phase 2.

## 5. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Trainer runtime | **Python 3.11+, PyTorch 2.x, CUDA 12.x** (bf16 autocast, `torch.compile` optional) | Where every model and every volunteer already is. CPU and Apple MPS backends supported for small jobs and for developer testing; CUDA is the first-class target |
| Training algorithm | **DiLoCo** inner/outer loop; reference from Prime Intellect's `OpenDiLoCo` / `prime` (Apache-2.0) | Proven at 1–100 B scale over WAN |
| Compression | **SparseLoCo / DeMo** style top-k + low-bit + error feedback; reference code from Templar (MIT) and Nous Psyche (Apache-2.0/MIT) | 100–500× bandwidth reduction, convergence proven |
| Tensor wire format | **safetensors** for checkpoints; custom flat binary frame (BLAKE3 hash, dtype, shape, packed indices + values) for compressed Δ | Zero-copy, no JSON (see audit: the old branches serialized matrices as JSON text) |
| Dataset format | **WebDataset** `.tar` shards of pre-tokenized `uint16`/`uint32` arrays, or images; content-addressed | Streamable, sliceable, cacheable, standard |
| Identity / signing | **Ed25519** (PyNaCl / `cryptography`), **BLAKE3** hashing | Fast, small, standard; same as Iroh node IDs |
| Coordinator API | **FastAPI** + **Pydantic v2** + **SQLAlchemy 2.0** on **PostgreSQL**; **Redis** for round timers and queues; **gRPC** streaming for trainer heartbeats and round events | Python keeps coordinator and trainer in one language; Postgres gives real transactions (the audited branch used SQLite and had a double-assignment race) |
| Blob storage | **S3-compatible** (Cloudflare R2 in production, MinIO locally); Phase 2: **Iroh** (Rust, QUIC, hole-punching, blobs + gossip) or **Hivemind** DHT for peer seeding | Start boring, add P2P where it reduces cost |
| Validator agent | Same Python package as trainer, `cudachain validator start` | One binary, two modes |
| Scoring | Templar **Gauntlet**-style loss-delta scoring, **OpenSkill** ratings (`openskill` PyPI) | Deployed in production for 72 B; MIT |
| Settlement (Phase 3) | **Solidity on Base** (OpenZeppelin, Foundry) or **Anchor on Solana**; Merkle-root payouts | Use an existing chain; both have public reference implementations in this space |
| Sandbox (Phase 3) | **Docker** with `--gpus`, no network, read-only rootfs, seccomp; **gVisor** when available | Standard GPU isolation story |
| CLI / SDK | **Typer** CLI, `pip install cudachain`, Python SDK | |
| Packaging / ops | `pyproject.toml` (uv/hatch), Docker images for coordinator and trainer, `docker compose` dev stack, GitHub Actions, **pytest** with a two-trainer in-process integration test | The audited branches had zero tests |
| Observability | Structured logs (structlog), Prometheus metrics, Grafana dashboard: loss per round, trainers online, bytes per round, score distribution | Trainers need a public leaderboard and requesters need a loss curve |

Deliberately **not** in the stack: a new blockchain, a new P2P protocol, JSON tensors,
C++ (until there is a measured hot path that PyTorch does not cover), raw CUDA kernels in
v1. The project name is kept because CUDA GPUs are the hardware the network runs on, not
because users write kernels.

## 6. Is it a server or a blockchain?

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

## 7. Going live: from laptop to first users

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
- **Trainer onboarding:** `pip install cudachain && cudachain trainer start --join <run>`
  or `docker run cudachain/trainer`. Minimum: NVIDIA GPU with ≥ 8 GB VRAM (RTX 3060 /
  3070 / 4060 Ti and up), Linux or WSL2, 20 Mbit/s upload, driver ≥ 535. Invite codes via
  Discord/GitHub; 10–50 people.
- **Verification:** validators run by the project only (2–3 GPUs), full Gauntlet scoring
  live, scores public. Credits accrue in the hash-chained ledger; not yet withdrawable.
  Leaderboard and "verified tokens trained" badge are the reward.
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
  rollout verification (the cheapest verifiable workload, see Prime Intellect in §8).

### Phase 4: scale

- Pipeline parallelism for models that do not fit one GPU (SWARM / IOTA / Pluralis style),
  which also changes the accounting (per-stage credit).
- Asynchronous rounds with staleness correction (HeLoCo / Decoupled DiLoCo).
- Governance of parameters and fees; token only if it is needed for something credits
  cannot do.

## 8. Prior art and competitors

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

## 9. Repository layout

Current state of the branches:

| Branch | Contents | Verdict |
|---|---|---|
| `main` | This README, `docs/` | Design |
| `development` | C++17 / Boost.Asio TCP mesh that ships 100×100 matrices as JSON for a CPU matmul (Aug–Sep 2024) | Does not compile (3-vs-7 argument mismatch, missing include path); double free in `Matrix`; results never returned. Archive |
| `initial-docs` | FastAPI + SQLite job-ticket API ("CPChain") and click CLI generated with Jules (May 2025) | Does not start (`NameError` ×3, missing deps, circular import in CLI); no P2P, no training. Archive |
| `jules_wip_8061578287170410081` | asyncio TCP message-passing skeleton with simulated worker (May 2025) | Daemon starts; CLI cannot talk to it; worker is `sleep(2)`. Archive |

Proposed layout for the rewrite (one Python monorepo):

```
cudachain/
├── pyproject.toml
├── docker-compose.yml            # postgres, redis, minio, coordinator, 2× trainer
├── src/cudachain/
│   ├── cli.py                    # typer: job | trainer | validator | ledger
│   ├── proto/                    # signed message schemas (pydantic) + gRPC defs
│   ├── crypto/                   # ed25519 identity, blake3 content addressing
│   ├── blobs/                    # s3 client, content-addressed cache, (phase 2) iroh/hivemind
│   ├── data/                     # webdataset sharding, deterministic assignment
│   ├── train/                    # diloco inner/outer loop, compression (sparseloco/demo), frames
│   ├── trainer/                  # agent: enrol, pull, train, commit-reveal, upload
│   ├── validator/                # agent: cheap checks, gauntlet scoring, re-execution
│   ├── coordinator/              # fastapi app, round state machine, aggregation, ledger
│   └── models/                   # allow-listed architectures (llama, gpt2, resnet, lora)
├── contracts/                    # phase 3: foundry project (escrow, payouts, bonds)
├── tests/                        # unit + two-trainer integration test
└── docs/
    ├── AUDIT.md                  # line-level audit of the old branches
    ├── LANDSCAPE.md              # competitor / research notes with sources
    └── PROTOCOL.md               # (to write) message formats and round state machine
```

## 10. Roadmap

- [ ] **M0 Scaffold.** `pyproject`, identity, signed messages, blob client, compose stack, CI.
- [ ] **M1 DiLoCo locally.** Inner/outer loop, SparseLoCo compression, binary Δ frames,
      two in-process trainers reach single-GPU loss on a 10–30 M model. Traffic measured.
- [ ] **M2 Coordinator.** Job spec, round state machine, deterministic assignment,
      commit-reveal, aggregation, hash-chained ledger, join/leave mid-run.
- [ ] **M3 Verification.** Gauntlet scoring, OpenSkill ratings, top-G selection, seeded
      cheating tests (random Δ, copied Δ, wrong shard) all detected.
- [ ] **M4 Alpha run.** VPS + R2, 150 M reference model, 10–50 invited trainers, public
      loss curve and leaderboard. (Phase 1 above.)
- [ ] **M5 Paid jobs.** Credits, Stripe/USDC in, USDC out, allow-listed fine-tune/LoRA jobs,
      community validators with bonds, P2P seeding. (Phase 2.)
- [ ] **M6 Contracts and quorum coordinator.** (Phase 3.)
- [ ] **M7 Pipeline parallelism, async rounds, custom code sandbox.** (Phase 4.)

## 11. Audit of the existing code

[`docs/AUDIT.md`](docs/AUDIT.md) lists every finding with file and line. The headline
items, because they shaped this design:

- **Nothing trains.** All three branches stop at the transport layer. The C++ branch
  multiplies matrices and throws the result away; the Python P2P branch "runs" a job with
  `asyncio.sleep(2)`; the FastAPI branch is a job-ticket table.
- **Nothing builds or starts except one daemon.** C++: declaration/definition mismatch on
  `send_matrix_to_peers`, wrong include path for nlohmann, header-defined non-inline
  functions. FastAPI: three `NameError`s at import, two missing dependencies, a circular
  import that kills the CLI. asyncio: `job submit` raises `TypeError` on its only code
  path and no CLI command can reach the running node.
- **Memory safety.** `Matrix` has a destructor but no copy constructor and is passed by
  value: guaranteed double free. `async_write` reads a stack variable after it has gone
  out of scope. Unbounded `resize()` from a network-supplied length.
- **No framing, no identity, no auth, no limits.** Both Python branches read a single
  4 KiB buffer and trust whatever arrives; the FastAPI branch signs JWTs with a hardcoded
  default secret if `.env` is missing and lets two workers take the same batch.
- **JSON tensors.** Matrices and (planned) weights are serialized as JSON text, 2–3 orders
  of magnitude too slow for model weights.
- **Aggregation was never designed.** Every README said "combine the weights" without an
  algorithm. That gap is now §2 and §3.3.

## 12. Contributing and license

The code in the historical branches is kept for reference only. New work happens on
`main` under the layout in §9, starting with M0. Issues are welcome, especially from people
with a consumer GPU who want to be alpha trainers, and from anyone who has run DiLoCo,
Hivemind, Psyche or Templar nodes.

License: to be decided before M4; the intended choice is **Apache-2.0** for the client and
coordinator (matching the ecosystem it builds on) with scoring code required to stay open.
