# Code audit — cuda-chain (all branches, October 2026)

This document records a line-level audit of every branch in the repository as of
commit `0f75ba2` on `main`. The short version: **none of the three implementations
is a viable foundation for distributed model training**, and two of them do not
start at all. The README proposes a from-scratch architecture informed by these
findings and by what has worked in comparable projects.

| Branch | Language / stack | Lines | Builds / runs? | What it actually is |
|---|---|---|---|---|
| `main` | — | 2 | n/a | One-line README only |
| `development` (merged `feat/initial-documentation`) | C++17, Boost.Asio, nlohmann/json, OpenSSL | ~1,100 | **No** (compile errors) | TCP mesh that ships 100×100 matrices as JSON for a CPU triple-loop matmul |
| `initial-docs` (Jules bot, May 2025) | Python, FastAPI, SQLAlchemy, SQLite, JWT, click | ~1,550 | **No** (import errors) | Centralised job-ticket API called "CPChain"; zero P2P, zero training |
| `jules_wip_8061578287170410081` (Jules bot, May 2025) | Python, asyncio TCP, JSON, click | ~1,250 | Daemon starts; CLI dead | Message-passing skeleton whose "worker" is `asyncio.sleep(2)` |

Common to all three: no CUDA code (despite the name), no model or dataset
transfer, no training loop, no gradient/weight aggregation, no verification of
work, no identity or signatures, no ledger, no rewards, no tests.

---

## 1. `development` — C++ P2P matmul prototype

Files: `main.cpp`, `p2p/Node.{h,cpp}`, `p2p/Peer.{h,cpp}`, `matrix/Matrix.{h,cpp}`,
`logger/Logger.h`, `utils/utils.h`, `utils/threaded_matmul.h`, `CMakeLists.txt`,
`build.sh`, `run.sh`.

### 1.1 Does not compile

| # | Location | Problem |
|---|---|---|
| C1 | `p2p/Node.h:134` vs `p2p/Node.cpp:260` | Header declares `send_matrix_to_peers(double**, double**, double**)` (3 params); the .cpp defines a 7-parameter overload that is never declared, and `main.cpp:64` calls the 3-param version which has no definition. Compile error + link error. |
| C2 | `p2p/Node.h:122`, `p2p/Peer.h:7` | `#include <nlohmann/json.hpp>` but CMake downloads the header to `./json.hpp` (no `nlohmann/` directory) and `matrix/Matrix.h:7` includes `<json.hpp>`. Only builds if nlohmann is also installed system-wide. |
| C3 | `p2p/Node.cpp:3` | `#include <uuid/uuid.h>` — unused, and `libuuid` is not in `CMakeLists.txt`. Fails on machines without `uuid-dev`. |
| C4 | `utils/utils.h:8`, `utils/threaded_matmul.h:9` | Non-`inline` function definitions in headers → multiple-definition link errors as soon as a second TU includes them. `utils.h` also has includes above its guard. |
| C5 | `CMakeLists.txt` | `Boost::system` only; Boost.Endian is header-only so fine, but no `find_package(Threads)` and `pthread` is linked by bare name. `.idea/` is committed. |

### 1.2 Memory-safety bugs (crash even if it compiled)

| # | Location | Problem |
|---|---|---|
| M1 | `matrix/Matrix.h:9-15`, `Matrix.cpp:234-240` | `Matrix` owns a raw `double**` with a destructor but **no copy constructor / copy assignment** (Rule of Three). `Matrix::multiply(Matrix)` and `add/subtract/...` take the argument **by value**, so `A.multiply(B)` at `Node.cpp:193` shallow-copies `B`, and the copy's destructor frees `B`'s rows → **double free** on every job. `from_array`/`from_json` returning by value rely on NRVO which is not guaranteed. |
| M2 | `p2p/Node.cpp:26` | `std::make_shared<Peer>(std::move(socket), socket.remote_endpoint()...)` — `remote_endpoint()` is evaluated on a possibly moved-from socket (argument evaluation order is unspecified). Throws `bad_descriptor` or returns garbage. |
| M3 | `p2p/Peer.cpp:70-86` | `write_message` puts the address of a **stack-local** `uint32_t length` into the `async_write` buffer list; the lambda does not capture it. The write happens after the function returns → dangling pointer, corrupted length prefix. Also multiple `async_write` calls overlap on the same socket with no outbound queue, which Asio explicitly forbids (interleaved bytes). |
| M4 | `p2p/Peer.cpp:45-46` | `message_length_` comes straight from the wire and is used in `read_buffer_.resize()` with no cap → any peer can request a 4 GiB allocation (memory DoS). |
| M5 | `matrix/Matrix.cpp:210-220` | `reshape()` indexes `data_[k / columns][k % columns]` with the *new* column count instead of `columns_` → out-of-bounds reads whenever shapes differ. |
| M6 | `matrix/Matrix.cpp:27-29` | `from_json` does `obj[0].size()` on possibly empty / non-array JSON → throws; no shape validation of remote payloads (`a_size`/`b_size` are sent but ignored). |

### 1.3 Concurrency bugs

| # | Location | Problem |
|---|---|---|
| T1 | `main.cpp:40-76`, `Node.cpp:294-299` | `send_periodic_messages` runs on its own `std::thread` and reads `peers_` (`get_peers()` copies an `unordered_set` while the io thread mutates it) and spins on `jobs_queue`/`compute_queue` in `wait()`, which the io thread pushes/pops. No mutex anywhere → data races / UB. |
| T2 | `Node.cpp:296` | `wait()` loops while `jobs_queue` is non-empty. Jobs are only popped when a `take_job_response` arrives; if any peer never answers, the dispatcher **hangs forever**. `compute_queue` is never written, so it is always empty. |
| T3 | `Peer.cpp:57,64` | After a body-read error, and for every error other than EOF/reset, `read_message()` is called again immediately → tight infinite loop on a closed socket (`operation_aborted`, `bad_descriptor`). |

### 1.4 Protocol / logic bugs

| # | Location | Problem |
|---|---|---|
| P1 | `Node.cpp:182-196` | The `job_data` handler computes `C = A.multiply(B)` and **discards it**. There is no `job_result` message type. The matrix `C` passed by `main.cpp` is never filled. The system computes nothing useful end-to-end. |
| P2 | `Node.cpp:262-288` | Rows are split as `rows_A / (peers+1)`; the local node's share (the "+1") is never computed and the remainder rows are silently dropped. Jobs are popped FIFO regardless of which peer accepted, so results could not be reassembled even if returned. |
| P3 | `Node.cpp:331` | `pop_job()` on empty returns `nlohmann::json("{}")` — a JSON **string** containing `{}`, not an empty object. The receiver then indexes a string → exception. |
| P4 | `Node.cpp:180`, `:146`, `:198` | Logs `json["id"]` on a message that has no `id` (null → string conversion throws `type_error.302`, caught, but aborts the rest of the handler). Same for numeric `source_port`. |
| P5 | `Node.cpp:26-28` | Accepted peers are registered with their **ephemeral** source port, then `broadcast_new_peer` tells everyone to connect to `ip:ephemeral_port` → connection failures and connect storms. Inbound peers are never added to `connected_peers_`, so A→B and B→A produce duplicate links. `Peer::operator==`/`std::hash<Peer>` are unused because the set stores `shared_ptr` (pointer identity). |
| P6 | `Peer.cpp:100-104`, `Node.cpp:205` | `handle_error` closes the socket but never removes the peer from `Node::peers_`; `broadcast_peer_disconnection` is never called; `peer_disconnected` is never handled. Dead peers accumulate and keep receiving writes. |
| P7 | `Node.cpp:148-164` | Any `take_job_request` is accepted while `compute_queue.size() < 100`; `compute_queue` is never pushed to, so every node accepts every request unconditionally. |
| P8 | `main.cpp:97-103` | Only the bootstrap node (no peer args) ever dispatches work; joiners get `run=false`. Acceptor binds IPv4 only. |
| P9 | `run.sh`, `Peer.h` | Generates TLS certs and includes `<boost/asio/ssl.hpp>` but SSL is commented out everywhere. All traffic is plaintext; no node identity, no authentication, no signatures. |

### 1.5 Performance

- Matrices are serialised as JSON doubles (~18–20 bytes each vs 8 raw; a 100×100 block is ~200 KB of text for 80 KB of data, with full parse cost). For model weights (10⁶–10¹⁰ parameters) this is 2–3 orders of magnitude too slow. Must be binary (safetensors / raw tensors / msgpack / protobuf).
- `Matrix::multiply` is a naive i-j-k triple loop with `matrix.get(k, j)` column access (cache-hostile). No BLAS, no CUDA. The project named "cuda-chain" contains no CUDA.
- `Matrix::dot`, `cross` and `inverse` are all element-wise (Hadamard / reciprocal), not the linear-algebra operations their names imply; `get_data()` returns an `int`.
- Every message is logged in full at INFO level including the serialised matrix body.

### 1.6 What is missing vs. the stated goal
Everything above the transport: job→peer mapping, result return, aggregation, model/dataset distribution, training, verification, identity, ledger, rewards, persistence, tests.

---

## 2. `initial-docs` — FastAPI "CPChain" backend + CLI

### 2.1 Does not start

| # | Location | Problem |
|---|---|---|
| F1 | `backend/models/user.py:76` | `ForeignKeyConstraint` used but never imported → `NameError` at import; every router import fails. (Redundant anyway: `worker_id` already has `ForeignKey("users.id")` at line 57.) |
| F2 | `backend/crud/request.py:39` | `Optional[int]` without importing `Optional` → `NameError`. |
| F3 | `backend/models/user.py:81` | `engine` undefined in a dead duplicate `create_db_and_tables()`. |
| F4 | `backend/core/config.py:2`, `routers/auth.py:25` | `python-dotenv` and `python-multipart` are required but absent from `requirements.txt`. |
| F5 | `cli/main.py:68` ↔ `cli/auth_commands.py:4` (and `requester_commands.py:5`, `worker_commands.py:4`) | Circular import. Verified: `python main.py --help` → `ImportError: cannot import name 'auth_group' from partially initialized module`. No console-script packaging, so the `cpchain` command in the README does not exist. **The CLI is 100 % non-functional.** |

### 2.2 Security

| # | Location | Problem |
|---|---|---|
| S1 | `backend/core/config.py:6` | `SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-for-jwt")`. With no `.env`, JWTs are signed with a public hardcoded key → anyone can mint a token for any user. Must fail hard at startup. |
| S2 | `backend/database.py:5` | DB URL hardcoded to SQLite; README and `.env.example` claim `SQLALCHEMY_DATABASE_URL` is honoured — it is read nowhere. |
| S3 | all routers | No roles. Any user is requester and worker; a requester can `take_batch` on its own request and mark it `completed` → trivial self-dealing once rewards exist. |
| S4 | `routers/auth.py` | No rate limiting, open registration, no `jti`/revocation, logout only deletes the local token file. |
| S5 | `schemas/request.py:25`, `routers/requests.py:25,51-52`, `worker.py:22-23` | `metadata` is an unbounded `Dict[str, Any]`; `num_batches` has no upper bound (`10_000_000` → 10 M rows in one transaction); `skip`/`limit` uncapped. |
| S6 | README | Instructs binding `--host 0.0.0.0` with no TLS; credentials and tokens cross the network in clear. |
| S7 | `requirements.txt` | Unpinned `passlib` (unmaintained since 2020) with modern `bcrypt` is a known-broken combination; passwords > 72 bytes silently truncated. |

### 2.3 Correctness / state machine

| # | Location | Problem |
|---|---|---|
| L1 | `routers/worker.py:52-60` | **Double-assignment race.** Read-then-commit; two concurrent workers both get HTTP 200 for the same batch id. Needs `UPDATE … WHERE status='pending'` with rowcount check. |
| L2 | `models/user.py:19-26` | `TrainingRequest.status` is never updated; 6 of 7 states unreachable. Guards against COMPLETED/FAILED at `worker.py:49` are dead code. |
| L3 | `routers/worker.py:90` | `/failed` maps to `PENDING`; `FAILED` is unreachable; no retry counter → a poisoned batch requeues forever. `IN_PROGRESS` never set. |
| L4 | — | No heartbeat/lease/timeout: a crashed worker strands its batch forever. README's "fault tolerance" and "24 h expiry" claims have no code (TODO marks expiry DONE while its own text says "Needs actual implementation"). |
| L5 | `routers/auth.py:16-19` | Register is check-then-insert → `IntegrityError` 500 on concurrent duplicate usernames. |
| L6 | `models/user.py` | No unique `(request_id, batch_number)`; no index on `request_batches.request_id` / `.status` although every worker query filters on them. |
| L7 | `cli/requester_commands.py:89` | CLI reads `metadata_json` but the API serialises by alias `metadata` → `request status` always prints `Metadata: {}`. |
| L8 | `routers/worker.py`, `routers/requests.py:43` | **Workers cannot obtain job metadata at all**: `/available` omits it, `take_batch` returns only the batch row, `/requests/{id}/status` is owner-only. There is no endpoint through which a worker could learn the model/dataset URL. |
| L9 | `cli/main.py:47-48` | Writes `~/.cpchain/config.json` as a side effect of any invocation, including `--help`. |
| L10 | README | Documents commands (`request download`, `worker join_network`, `leave_network`) that do not exist; two sections of the README disagree with each other and with the code. |

### 2.4 Performance
SQLite single-writer with `check_same_thread=False` under FastAPI's threadpool → "database is locked" at modest concurrency. N+1 lazy loads (`len(req.batches)` per listed request; full `batches` serialised per item in `GET /requests/`). Correlated `.any()` subquery with no index. No background scheduler, so expiry/timeouts cannot be implemented without a runtime redesign. SQLAlchemy 1.x and Pydantic v1 idioms throughout.

### 2.5 Missing vs. stated goal
P2P layer (undecided between libp2p/WebRTC/sockets, nothing chosen), worker addressing, model/dataset transfer, training loop, weight upload/storage/download, **weight aggregation (not even designed — the README has N workers each train on one batch and never says how the N divergent weight sets are combined)**, rewards ("Conceptual"), validation, sandboxing, tests, CI, Dockerfile, `.gitignore`, migrations.

---

## 3. `jules_wip_8061578287170410081` — asyncio P2P job skeleton

### 3.1 Showstoppers

| # | Location | Problem |
|---|---|---|
| J1 | `cuda_chain/cli.py:292-298` vs `network.py:242` | `submit_job_async` passes `kernel_file_path=…` kwargs to a method whose parameters are `kfp, ifp, gds, bds, tnas` → `TypeError` on the only submission path. Verified at runtime. |
| J2 | `cuda_chain/cli.py:8` | `network_manager_instance` is a module global; every subcommand runs in a new process where it is `None` → `node leave`, all `job *`, `node ping/status/list`, `network status` always print "Node not started". No IPC between CLI and daemon. Only `node start` works. |
| J3 | `cuda_chain/network.py:48-50` | `GET_PEERS` excludes the bootstrap node itself, so after joining a fresh bootstrap the joiner has **zero peers**. Verified: `A.peers=['B']`, `B.peers=[]`. Later joiners are invisible to earlier ones; no gossip. |
| J4 | `network.py:268-279` + `291-301` | The submitter appends its own job to `pending_jobs` "for tracking" and its own processor loop **executes it too** → every job runs twice, and the two `completed` updates race. Verified. |
| J5 | `network.py:323-329` | The worker is `await asyncio.sleep(2)` followed by `result_data = "Simulated result for job …"`. `pycuda` is in `requirements.txt` and never imported. **No CUDA code exists.** |
| J6 | `job.py:13-16` | `kernel_file_path` / `input_file_path` are **path strings on the submitter's disk**; the bytes are never read or sent. `kernel_code` exists and is never populated. |

### 3.2 Networking

| # | Location | Problem |
|---|---|---|
| N1 | `network.py:30`, `:198` | Single `read(4096)` on both sides, no framing. Any message > 4 KiB (a 30-peer `PEERS_LIST`, any real payload) truncates mid-JSON → silently dropped. |
| N2 | `network.py:180-220` | One TCP connection per message, including every status update. |
| N3 | `network.py:211-215` | Dead-peer eviction is commented out; dead peers stay first in dict order and keep being chosen as the job target (`list(self.peers.values())[0]`, `:286`). |
| N4 | `cli.py:47`, `network.py:11-16` | Binds and **advertises** `0.0.0.0` → peers try to connect to `0.0.0.0:port`; works only on one machine. |
| N5 | `network.py:29-31` | No per-connection timeout → trivial slow-loris. |
| N6 | `cli.py:170`, `network.py:537` | `split(':')` breaks IPv6. |

### 3.3 Security
No authentication of any message. `ANNOUNCE` with arbitrary `node_info` poisons peer tables; `NODE_LEAVING` with any `sender_node_id` evicts arbitrary peers; `REQUEST_JOB_CANCEL` cancels anyone's job; `sender_node_id` overwrites `job.submitter_node_id` (`network.py:59`). JSON wire format, so no RCE *today* — but the design intent (compile a remote `.cu` with pycuda) is unsandboxed arbitrary native code on volunteer GPUs.

### 3.4 Logic
`network.py:372` and `:519` compare against `"active_jobs"` while the variable holds `"active"` → submitter-side jobs never move to `completed`. `status == "cancelling"` (`:304`) is never set. Cancel of a running job is overwritten by the still-running coroutine which re-inserts it as `completed` (`:334`). `__repr__` and several CLI lines slice `submitter_node_id[:8]` without a `None` guard. `click.echo(..., fg=…)` at `cli.py:411` is a `TypeError`. `tests/*.py` are **0 bytes**.

### 3.5 Performance
Single serial worker coroutine with a 1 s poll; `pending_jobs`/`completed_jobs`/`peers` unbounded; `list.pop(0)` and linear scans everywhere; full job dict re-sent on every state transition; `resources` hardcoded to `{"cuda_cores": 0, "memory_gb": 0}`.

---

## 4. Cross-cutting conclusions

1. **The transport layer was rewritten three times and the hard parts were never started.** The three branches are three different P2P/RPC skeletons (Asio, asyncio, FastAPI). None contains a training step, an aggregation step, a verification step or a ledger. Writing a fourth bespoke transport is the wrong next move; the mature building blocks already exist (see README §"Architecture" and §"Prior art").
2. **Weight aggregation is undesigned.** Every branch's README assumes "each trainer trains a batch, then combine the weights" without specifying *how*. Naïve averaging of independently-trained weights from the same init diverges after a few hundred steps. The field's answer is local-SGD / DiLoCo-style pseudo-gradient averaging with an outer optimiser, or federated averaging per round. This is the core algorithm and must be chosen first.
3. **JSON is unusable as a tensor wire format.** Both C++ and Python branches serialise numbers as text. Tensors must move as raw bytes (safetensors, NumPy, Arrow, or protobuf/flatbuffer frames), compressed and quantised for the outer-loop sync.
4. **"Blockchain" has no code and no design in any branch.** Before writing one, decide whether a chain is needed at all for v0 (it is not — a signed append-only log with a central coordinator is enough to launch) and which chain to *settle* on later rather than building one.
5. **Security was deferred everywhere.** Any of the three nodes would execute or accept arbitrary remote input with no identity, no signatures, no sandbox. For a network that runs user-submitted model code on volunteer GPUs, this is the first problem, not the last.

The README's architecture section is the proposed replacement.
