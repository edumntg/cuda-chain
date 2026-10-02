# Decentralized AI training: landscape and research notes

Compiled October 2026 to inform the plasmon design. Claims link to a primary source
where one was found; funding and token figures are from press coverage and should be
re-checked before being quoted externally.

## 1. One-paragraph takeaway

Internet-scale pre-training over commodity links is proven at 7–100 B scale by four
independent groups (Templar/Covenant 72 B, Macrocosmos Orion-100B, Pluralis 8 B on 330
consumer GPUs, Nous Consilience 40 B), and decentralized RL post-training at 32 B
(Prime Intellect INTELLECT-2). Every working system converges on the same recipe:
DiLoCo-style local SGD with infrequent outer steps; aggressive DCT/top-k/low-bit
compression of pseudo-gradients (DeMo, SparseLoCo, DisTrO); a logically central
coordinator (a Solana program, a Bittensor validator set, a Rust orchestrator) over
physically decentralized workers; and reward settlement on an existing chain. Nobody has
solved cheap, general verification of training work; the practical answer is
economic/statistical verification (loss delta on held-out data, random re-execution,
OpenSkill/Shapley-style ratings) rather than cryptographic proofs. Commercially, the
best-funded players train their flagship models on centralized InfiniBand clusters;
Gensyn shipped a token but not a training mainnet; Covenant left Bittensor over
governance. The gap for a new project is not "a P2P layer" but incentive design,
verification UX and job-submission ergonomics on top of existing open-source stacks.

## 2. Project by project

### 2.1 Bittensor and its training subnets

**Bittensor (TAO)** is an incentive layer, not a training system: subnets define a task,
*miners* produce work, *validators* score it, and Yuma Consensus turns validator weights
into emissions. Validator scoring is off-chain and unverifiable, which is the central
trust assumption critics point at
([analysis](https://medium.com/@TensorExchange/bittensor-whitepaper-vs-reality-b7f94e559499)).
dTAO (2025) gave each subnet its own alpha token; subnet tokens reached ~$1.5 B in
March 2026 ([CoinDesk](https://www.coindesk.com/tech/2026/03/25/bittensor-ecosystem-tokens-value-hit-usd1-5-billion-as-jensen-huang-endorsement-supports-tao-rally)).

**Templar (SN3) / Covenant AI.** The closest existing system to the plasmon idea:
miners each train on a shard, submit compressed pseudo-gradients, and are paid in
proportion to measured contribution.

- Mechanism (Gauntlet, [arXiv 2505.21684](https://arxiv.org/abs/2505.21684)):
  deterministic per-miner data assignment `SelectData(seed, uid, window)`; local steps;
  DeMo compression (DCT + top-k); upload to Cloudflare R2 with commit-reveal timing.
  Validators run a cheap pass on everyone (timeliness, tensor shape, sync score against
  the validator's own state; 0.75 penalty on failure) and an expensive pass on ~5 random
  peers per window computing `LossScore = L(θ) − L(θ − βΔ)` on both the miner's assigned
  data and random data. The sign of (assigned − random) accumulates: honest miners trend
  positive, copiers and free-riders trend to zero. OpenSkill ratings; score² normalisation;
  top-G = 15 gradients aggregated with equal weight. Acknowledged weaknesses: a bad update
  can land before down-weighting; aggregation is not Byzantine-robust; a single
  highest-stake validator picks checkpoints; everything routes through a cloud bucket.
- Results: Templar-1B in the paper; **Covenant-72B** (72.7 B params, ~1.09 T tokens,
  Sept 2025 – Mar 2026, 70+ permissionless nodes, MMLU 67.1, Apache-2.0) using
  **SparseLoCo** (error-feedback top-k 1–3 % + 2-bit, >146× communication reduction)
  ([write-up](https://blockeden.xyz/blog/2026/03/13/templar-covenant-72b-bittensor-largest-decentralized-llm-pretraining/),
  [SparseLoCo arXiv 2508.15706](https://arxiv.org/pdf/2508.15706)).
- Code: Python/PyTorch, MIT, [github.com/tplr-ai/templar](https://github.com/tplr-ai/templar).
- Status: Covenant AI exited Bittensor on 10 April 2026 calling it "decentralization
  theatre" ([Unchained](https://unchainedcrypto.com/covenant-ai-calls-bittensor-decentralization-theatre-exits-network-as-tao-falls-15-unchained/),
  [tao.media](https://www.tao.media/covenant-ais-bittensor-exit-what-happened-how-bittensor-responded-and-whats-next-for-the-network/)).
  SN3 was re-registered as **Teutonic**, a king-of-the-hill scheme (lowest loss challenger
  takes all emissions) training an 80 B model since May 2026
  ([tao.media](https://www.tao.media/teutonic-subnet-begins-training-80b-ai-model-on-bittensor-marking-largest-decentralized-training-run-yet/)).

**IOTA (SN9) / Macrocosmos.** Pipeline-parallel alternative.

- Mechanism ([arXiv 2507.17766](https://arxiv.org/pdf/2507.17766),
  [docs](https://docs.macrocosmos.ai/subnets/subnet-9-iota)): a hub-and-spoke
  orchestrator assigns each miner one pipeline stage (so per-node VRAM no longer bounds
  model size) and streams activations between stages; a bottleneck block compresses
  inter-stage activations up to 128×; data-parallel replicas merge via Butterfly
  All-Reduce; CLASP does Shapley-inspired credit assignment; validators recompute sampled
  sections and compare by cosine similarity; tolerates ~35 % miner failure.
- Results: Orion-100B proof of concept (16 PP stages × 3 replicas on geo-distributed
  A100s, >30 % MFU, halted after two days for budget reasons)
  ([announcement](https://x.com/MacrocosmosAI/status/2061493162582118695)); Orion-16B live
  on ~180 heterogeneous GPUs; "Train at Home" Mac app open to the public since Feb 2026
  ([docs](https://docs.macrocosmos.ai/product-and-services/tah)).
- Code: [github.com/macrocosm-os/iota](https://github.com/macrocosm-os/iota) (Python).

**Gradients (SN56, Rayon Labs).** Fine-tuning marketplace: upload data, miners compete
on the best fine-tune ([gradients.io](https://www.gradients.io/)). A competition model,
not shard-and-aggregate, but the only live "third party submits a job" product.

### 2.2 Prime Intellect

- Lineage: **OpenDiLoCo** ([arXiv 2407.07852](https://arxiv.org/pdf/2407.07852))
  reimplemented DiLoCo on Hivemind, 1.1 B across two continents at 90–95 % utilisation.
  **INTELLECT-1** (Nov 2024): 10 B, 1 T tokens, up to 112 H100s / 14 nodes on three
  continents, 83 % utilisation, int8 pseudo-gradients, elastic join/leave.
  **INTELLECT-2** ([arXiv 2505.07291](https://arxiv.org/html/2505.07291)): 32 B, first
  permissionless decentralized RL run: prime-rl (async GRPO) + SHARDCAST (tree weight
  broadcast) + **TOPLOC** ([arXiv 2501.16007](https://arxiv.org/pdf/2501.16007); a
  locality-sensitive hash of top-k hidden states that verifies inference rollouts up to
  100× faster than generating them) + contracts on Base Sepolia. Key insight: in RL the
  expensive part (rollouts) is inference, which is cheaply verifiable; the trainer stays
  centralized.
- Status: **INTELLECT-3** (Nov 2025, 106 B MoE) was trained on a centralized 512× H200
  InfiniBand cluster ([commentary](https://www.implicator.ai/prime-intellects-intellect-3-open-source-ambition-meets-centralized-reality/)).
  The Rust protocol repo was archived in Jan 2026
  ([github](https://github.com/PrimeIntellect-ai/protocol)). No token. $130 M Series A at
  $1 B valuation (Jul 2026) ([SiliconANGLE](https://siliconangle.com/2026/07/08/prime-intellect-raises-130m-1b-valuation-ai-training-platform/)).
- Code: `prime` (OpenDiLoCo), `prime-rl`, `verifiers`, `toploc`: Python, open.

### 2.3 Nous Research (DisTrO / DeMo, Psyche)

- Technique: **DeMo** ([arXiv 2411.19870](https://arxiv.org/abs/2411.19870)) decouples
  momentum, DCT-transforms it and ships only top-k fast components; DisTrO adds 1-bit sign
  quantisation.
- Architecture ([nousresearch.com/nous-psyche](https://nousresearch.com/nous-psyche)):
  coordinator = **Solana programs (Anchor/Rust)** holding run metadata, participants, the
  phase state machine and randomness for data assignment and witness election. P2P via
  **Iroh** (QUIC, Ed25519 node IDs, hole punching, ~90 % direct connections). Witnesses
  attest result availability via bloom filters; verification is statistical (similarity
  of recomputed vs submitted compressed updates within a calibrated tolerance).
- Results: Consilience 40 B (last public checkpoint Aug 2025); **Hermes 4.3 (36 B)**
  trained start to finish on Psyche across 24 nodes
  ([Nous](https://nousresearch.com/the-next-phase-of-psyche)). Apache-2.0/MIT, Rust.
  No token, no incentives yet. $50 M Series A led by Paradigm (Apr 2025)
  ([SiliconANGLE](https://siliconangle.com/2025/04/25/nous-research-raises-50m-decentralized-ai-training-led-paradigm/)).

### 2.4 Gensyn

- Verification stack: **Verde** ([arXiv 2502.19405](https://arxiv.org/abs/2502.19405)),
  refereed delegation: run the job on ≥ 2 untrusted providers; on disagreement a referee
  bisects the graph and re-executes one operator. Requires **RepOps**, bitwise-deterministic
  kernels across GPUs. Correct if one provider is honest; cost is replication. Also
  NoLoCo, SkipPipe, CheckFree, SAPO.
- Status ([docs](https://docs.gensyn.ai/testnet)): testnet Mar 2025 (RL Swarm on 0.5–1.5 B
  Qwen); RL Swarm paused Jan 2026; Ethereum L2 "mainnet" Apr 2026 whose first app is a
  prediction market; $AI token Apr 2026; **training mainnet not live**. **Open-1B**
  (Sept 2026): 1 B model trained centrally on 48× H100 with every step fingerprinted so
  anyone can replay and verify ([Gensyn](https://www.gensyn.ai/news/introducing-open-1b-auditable-training),
  [arXiv 2609.17380](https://arxiv.org/html/2609.17380v1)).

### 2.5 Pluralis Research (Protocol Learning)

- Thesis: model-parallel so no participant ever holds full weights
  ([arXiv 2605.23464](https://arxiv.org/pdf/2605.23464)); **Subspace Networks** compress
  inter-stage activations and gradients up to 100× ([blog](https://pluralis.ai/blog/beyond-top-k-pipeline-parallelism/)).
- Results: **Node0-7.5B**: 36 B tokens, 3 weeks, 300+ participants, 1,642 GPUs from 198
  cities, 16 GB consumer GPUs eligible ([github](https://github.com/PluralisResearch/node0));
  **Pluralis-8B** ([arXiv 2607.13332](https://arxiv.org/abs/2607.13332)): 500 B tokens,
  330 nodes, 40 days, ~63 % of an H100 cluster's efficiency. Node0 is Python on Hivemind,
  Apache-2.0. $7.6 M seed (Mar 2025) ([USV](https://blog.usv.com/pluralis-towards-actually-open-ai-1)).
  No token; reputational rewards.

### 2.6 Hivemind / Petals / SWARM

- **Hivemind** ([github](https://github.com/learning-at-home/hivemind)): PyTorch library,
  libp2p DHT, decentralized parameter averaging over unreliable peers, decentralized MoE.
  MIT. v1.1.12 released Jan 2026 ([PyPI](https://pypi.org/project/hivemind/)); the
  substrate for OpenDiLoCo and Node0.
- **SWARM Parallelism** ([arXiv 2301.11913](https://arxiv.org/abs/2301.11913)):
  randomised self-healing pipelines over preemptible heterogeneous nodes; ancestor of IOTA
  and Pluralis.
- **Petals** ([github](https://github.com/bigscience-workshop/petals)): BitTorrent-style
  inference/fine-tuning of 100 B+ models; public swarm effectively in maintenance mode.

### 2.7 Federated learning frameworks

- **Flower** ([flower.ai](https://flower.ai/)): dominant FL framework; **Photon**
  ([arXiv 2411.02908](https://arxiv.org/pdf/2411.02908)) did federated LLM pre-training
  up to 7 B with 64–512× less communication. Trust model is honest-but-curious data
  owners, not anonymous paid compute; no token, no Sybil defence.
- **FedML → TensorOpera**: pivoted to a general AI cloud.

### 2.8 GPU marketplaces (rent machines, do not coordinate training)

Akash (TEE confidential compute Jul 2026; deprecating its own chain), io.net (~370 k GPUs
claimed), Render (absorbed Salad's ~60 k consumer GPUs, Apr 2026), Golem, Vast.ai. They
sell GPU-hours, not training steps: suppliers to and a distribution channel for a training
protocol, not competitors.

### 2.9 Adjacent

- **Together AI**: born from decentralized-training research
  ([NeurIPS 2022](https://arxiv.org/pdf/2206.01288)), abandoned it, now a neocloud at
  $8.3 B ([TechCrunch](https://techcrunch.com/2026/07/01/neocloud-together-ai-raises-800m-leaps-to-8-3b-valuation/)).
- **Exo** ([github](https://github.com/exo-explore/exo)): LAN clusters for inference.
- **DiLoCoX** (0G Labs + China Mobile, [arXiv 2506.21263](https://arxiv.org/pdf/2506.21263)):
  107 B over 1 Gbps links, 357× less communication than all-reduce, across cooperating
  datacentres.
- **Fortytwo** ([arXiv 2510.24801](https://arxiv.org/html/2510.24801)): peer-ranked swarm
  inference; **BlockTrain** ([arXiv 2606.24722](https://arxiv.org/abs/2606.24722)):
  block-wise training with local objectives.

## 3. Core research lineage

| Paper | Idea | Communication reduction |
|---|---|---|
| DiLoCo ([2311.08105](https://arxiv.org/abs/2311.08105)) | Inner AdamW for ~500 local steps, outer Nesterov on pseudo-gradients | ~500× |
| Streaming DiLoCo ([2501.18512](https://huggingface.co/papers/2501.18512)) | Sync parameter subsets in rotation, overlap communication, 4-bit | ~400×, lower peak bandwidth |
| DiLoCo scaling laws ([2503.09799](https://arxiv.org/pdf/2503.09799)) | Stable hyper-parameters across scale; advantage grows with model size | |
| Decoupled DiLoCo ([2604.21428](https://arxiv.org/pdf/2604.21428)) | Async learners, quorum/time-window merging | |
| DeMo / DisTrO ([2411.19870](https://arxiv.org/abs/2411.19870)) | DCT top-k of momentum, 1-bit sign | 100–1000× |
| SparseLoCo ([2508.15706](https://arxiv.org/pdf/2508.15706)) | Error-feedback top-k 1–3 % + 2-bit; beats dense DiLoCo | >100× |
| HeLoCo ([2606.00271](https://arxiv.org/abs/2606.00271)) | Direction-aware correction of stale pseudo-gradients under heterogeneity | +22 % vs sync under heavy heterogeneity |
| SWARM ([2301.11913](https://arxiv.org/abs/2301.11913)), Protocol Models, IOTA | Pipeline parallel over WAN with activation compression | 100–128× on activations |
| Epoch AI ([analysis](https://epochai.substack.com/p/how-far-can-decentralized-training)) | Naïve DP at 60 Mbps caps at ~600 M params; largest decentralized runs ~1000× below frontier FLOP; decentralized compute growing ~20×/yr | |

## 4. Verification literature

- **Proof-of-Learning** ([arXiv 2103.05633](https://arxiv.org/abs/2103.05633)): log
  checkpoints, verifier replays sampled segments. Spoofable at under 1/10 of honest cost
  ([2208.03567](https://arxiv.org/pdf/2208.03567)); incentive-security variants exist
  ([2404.09005](https://arxiv.org/pdf/2404.09005)).
- **Deterministic replay** (Gensyn Verde/RepOps, Open-1B): sound but needs bitwise
  reproducible kernels and ≥ 2× replication.
- **Statistical / economic** (Templar Gauntlet, IOTA CLASP, Psyche similarity tolerances,
  Bittensor validator consensus): cheap, used by every live network; tunable thresholds
  and "one bad update before detection" remain.
- **Inference-side** (TOPLOC): works because RL rollouts are inference; the only cheap,
  scalable verification in production.
- **Pipeline-specific** (SENTINEL, [2603.03592](https://arxiv.org/abs/2603.03592)):
  activation monitoring across untrusted pipeline workers without duplication.
- **Byzantine aggregation** (Giskard, [2606.19129](https://arxiv.org/abs/2606.19129);
  and the finding that a plain weighted mean is often more robust than fancy aggregators
  under heterogeneity, [2601.02682](https://arxiv.org/pdf/2601.02682)).

## 5. Synthesis

**What has proven to work.** Local-SGD data parallelism with infrequent outer steps;
aggressive pseudo-gradient compression; pipeline parallelism with compressed activations
to escape per-node memory limits; asynchrony and fault tolerance designed in from the
start; decentralized RL post-training as the lowest-friction verifiable workload.

**The common architecture.** A logically central, auditable coordinator (contract,
validator set or orchestrator) handles membership, assignment seeds, phase transitions
and scoring; physically decentralized workers pull shards, train and push compressed
updates over a P2P blob layer or object storage; rewards settle on an existing chain.
Fully P2P gossip aggregation remains research.

**Unsolved problems.** General, cheap, sound verification of training work;
Byzantine/poisoned updates landing before detection; free-riding and Sybils under
validator collusion; stragglers and heterogeneous hardware; bandwidth and NAT at 70 B
scale; per-node memory without pipeline parallelism; economics at the frontier.

**Where a small project can differentiate.** (1) A permissionless job market where third
parties submit model + dataset, which no live network offers beyond fine-tune competitions.
(2) Starting with verifiable workloads: fine-tunes, LoRA, RL rollouts. (3) Transparent,
recomputable scoring as a product, in direct contrast to black-box validators. (4)
Heterogeneity-native scheduling and consumer-GPU/Mac support. (5) Credible neutrality
about who can switch off rewards.

**What to avoid.** A new L1, promises of frontier pre-training, cryptographic
proof-of-learning, or a fully P2P all-reduce as v1.
