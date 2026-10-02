"""`python -m plasmon`: plain-text commands for the engine. The Rust `plasmon` binary
calls into these for the steps that need PyTorch and adds the TUI."""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import sys
import time
import webbrowser
from collections.abc import Callable, Sequence
from pathlib import Path

from . import __version__, credentials
from .client import ApiError, Client
from .paths import machine_key_path

Handler = Callable[[argparse.Namespace], int]


def _print(args: argparse.Namespace, data, text: str | None = None) -> None:
    if getattr(args, "json", False):
        print(json.dumps(data, default=str, indent=2))
    elif text is not None:
        print(text)


def _client(args: argparse.Namespace, need_login: bool = True) -> Client:
    server = getattr(args, "server", None)
    creds = credentials.load_user()
    if server is None and creds is not None:
        server = creds.server
    if server is None:
        raise SystemExit("not logged in. Run: plasmon login --server http://<host>:7117")
    token = creds.token if creds and creds.server == server.rstrip("/") else None
    if need_login and token is None:
        raise SystemExit(f"not logged in to {server}. Run: plasmon login --server {server}")
    return Client(server, token)


def _fmt_table(rows: list[list[str]], headers: list[str]) -> str:
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    line = "  ".join(str(h).ljust(w) for h, w in zip(headers, widths))
    out = [line]
    for r in rows:
        out.append("  ".join(str(c).ljust(w) for c, w in zip(r, widths)))
    return "\n".join(out)


# ----- identity and login --------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    from .core.identity import Identity

    path = machine_key_path()
    if path.exists() and not args.force:
        ident = Identity.load(path)
        _print(args, {"node_id": ident.node_id, "path": str(path), "created": False}, f"machine key exists: {path}\nnode id: {ident.node_id}")
        return 0
    ident = Identity.generate()
    ident.save(path)
    _print(args, {"node_id": ident.node_id, "path": str(path), "created": True}, f"created machine key: {path}\nnode id: {ident.node_id}")
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    server = args.server.rstrip("/")
    client = Client(server)
    try:
        client.healthz()
    except Exception as e:  # unreachable, wrong port, not a plasmon server
        print(f"cannot reach {server}: {e}", file=sys.stderr)
        return 1
    if args.email:
        password = args.password or getpass.getpass("password: ")
        out = client.login(args.email, password, label=f"cli on {_hostname()}")
    else:
        start = client.device_start(label=f"cli on {_hostname()}")
        url = start["verification_uri_complete"]
        print(f"Open this address in a browser and confirm the code.\n\n  {url}\n\n  code: {start['user_code']}\n")
        if not args.no_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        deadline = time.time() + start["expires_in"]
        out = None
        while time.time() < deadline:
            time.sleep(start["interval"])
            reply = client.device_poll(start["device_code"])
            if reply.get("status") != "pending":
                out = reply
                break
            print(".", end="", flush=True)
        print()
        if out is None:
            print("code expired; run login again", file=sys.stderr)
            return 1
    credentials.save_user(credentials.UserCredentials(server, out["user"]["email"], out["token"]))
    _print(args, {"server": server, "user": out["user"]}, f"logged in to {server} as {out['user']['email']} ({out['user']['role']})")
    return 0


def cmd_logout(args: argparse.Namespace) -> int:
    creds = credentials.load_user()
    if creds:
        try:
            Client(creds.server, creds.token).post("/v1/auth/logout")
        except Exception:
            pass
        credentials.clear_user()
    print("logged out")
    return 0


def cmd_whoami(args: argparse.Namespace) -> int:
    from .core.identity import Identity

    creds = credentials.load_user()
    key = machine_key_path()
    node_id = Identity.load(key).node_id if key.exists() else None
    data = {"node_id": node_id, "server": creds.server if creds else None, "user": creds.user if creds else None, "role": None}
    if creds:
        try:
            data["role"] = Client(creds.server, creds.token).me()["user"]["role"]
        except Exception as e:
            data["error"] = str(e)
    lines = [f"node id: {node_id or '(none; run plasmon init)'}"]
    lines.append(f"server:  {creds.server}\nuser:    {creds.user} ({data.get('role') or 'unknown role'})" if creds else "not logged in")
    _print(args, data, "\n".join(lines))
    return 0


def _hostname() -> str:
    import platform

    return platform.node() or "machine"


# ----- server ----------------------------------------------------------------------------

def cmd_server_init(args: argparse.Namespace) -> int:
    from .coordinator import config

    cfg = config.ServerConfig(mode=args.mode, port=args.port, org_name=args.org, public_url=args.public_url)
    if args.mode != "home":
        cfg.auth.open_registration = False
    path = config.write(cfg, Path(args.config) if args.config else None)
    _print(args, {"config": str(path), "data_dir": str(cfg.resolved_data_dir())}, f"wrote {path}\ndata dir: {cfg.resolved_data_dir()}\nnext: plasmon server start")
    return 0


def cmd_server_start(args: argparse.Namespace) -> int:
    from .coordinator import run

    return run.main([args.config] if args.config else [])


def cmd_server_bootstrap(args: argparse.Namespace) -> int:
    """Create the owner account directly in the database, for a server with no users yet."""
    import secrets

    from sqlalchemy import func, select

    from .coordinator import auth, config, db

    cfg = config.load(Path(args.config) if args.config else None)
    engine = db.make_engine(cfg.resolved_db_url())
    with db.make_session_factory(engine)() as session:
        if session.scalar(select(func.count()).select_from(db.User)):
            print("the server already has users; use the dashboard to manage them", file=sys.stderr)
            return 1
        password = args.password or secrets.token_urlsafe(12)
        user = db.User(email=args.owner.lower(), name=args.name or "", password_hash=auth.hash_password(password), role="owner")
        session.add(user)
        session.commit()
    _print(args, {"email": args.owner, "password": password}, f"owner created: {args.owner}\npassword: {password}\nlog in at the dashboard and change it in Account.")
    return 0


def cmd_server_status(args: argparse.Namespace) -> int:
    client = _client(args)
    status = client.server_status()
    text = (
        f"version {status['version']}  mode {status['mode']}  uptime {status['uptime_s']} s\n"
        f"db {status['db']['url']} ({status['db']['ping_ms']} ms)\nblobs {status['blobs']['bytes']:,} B at {status['blobs']['path']}\n"
        f"scheduler running: {status['scheduler']['running']}  sse clients: {status['sse_clients']}\n"
        f"ledger entries {status['ledger']['entries']}  head {status['ledger']['head'][:16]}…\n"
        f"users {status['counts']['users']}  machines {status['counts']['machines']}  jobs {status['counts']['jobs']} ({status['counts']['jobs_running']} running)"
    )
    _print(args, status, text)
    return 0


# ----- jobs ------------------------------------------------------------------------------

def cmd_job_submit(args: argparse.Namespace) -> int:
    from . import jobs
    from .core import jobspec

    spec = jobspec.load(args.file)
    client = _client(args)
    job = jobs.submit(client, spec)
    url = f"{client.server}/jobs/{job['id']}"
    _print(args, job, f"submitted {job['name']} as {job['id']}\n  rounds: {job['total_rounds']}  shards: {job['shards']}  params: {job['param_count']:,}\n  watch: plasmon job watch {job['id']}\n  page:  {url}")
    return 0


def _job_rows(jobs: list[dict]) -> list[list[str]]:
    return [[j["id"], j["name"], j["status"], f"{j['round']}/{j['total_rounds']}", f"{j['eval_loss']:.3f}" if j["eval_loss"] is not None else "", f"{100 * j['eval_acc']:.1f} %" if j["eval_acc"] is not None else ""] for j in jobs]


def cmd_job_list(args: argparse.Namespace) -> int:
    jobs = _client(args).jobs(all=args.all)
    _print(args, jobs, _fmt_table(_job_rows(jobs), ["id", "name", "status", "round", "eval loss", "eval acc"]) if jobs else "no jobs")
    return 0


def cmd_job_status(args: argparse.Namespace) -> int:
    job = _client(args).job(args.id)
    rows = [[r["index"], r["status"], r["accepted"], f"{r['eval_loss']:.4f}" if r["eval_loss"] is not None else "", f"{100 * r['eval_acc']:.1f} %" if r["eval_acc"] is not None else "", f"{r['bytes_in']:,}"] for r in job["rounds"]]
    head = f"{job['name']} ({job['id']})  {job['status']}  round {job['round']}/{job['total_rounds']}  params {job['param_count']:,}"
    _print(args, job, head + "\n" + _fmt_table(rows, ["round", "status", "trainers", "eval loss", "eval acc", "bytes in"]))
    return 0


def cmd_job_watch(args: argparse.Namespace) -> int:
    client = _client(args)
    seen = -1
    while True:
        job = client.job(args.id)
        for r in job["rounds"]:
            if r["status"] == "closed" and r["index"] > seen:
                seen = r["index"]
                print(f"round {r['index']:>4}  trainers {r['accepted']:>3}  eval loss {r['eval_loss']:.4f}  acc {100 * r['eval_acc']:.1f} %  {r['bytes_in']:,} B in")
        if job["status"] != "running":
            print(f"job {job['status']}" + (f": {job['status_detail']}" if job["status_detail"] else ""))
            return 0 if job["status"] == "completed" else 1
        time.sleep(args.interval)


def cmd_job_download(args: argparse.Namespace) -> int:
    client = _client(args)
    job = client.job(args.id)
    out = Path(args.output or f"{job['name']}.safetensors")
    out.write_bytes(client.get_blob(job["theta"]))
    _print(args, {"path": str(out), "blob": job["theta"], "round": job["round"]}, f"wrote {out} (weights after round {job['round']}, blob {job['theta'][:12]}…)")
    return 0


def cmd_job_cancel(args: argparse.Namespace) -> int:
    job = _client(args).cancel_job(args.id)
    _print(args, job, f"job {job['id']} {job['status']}")
    return 0


# ----- trainer ---------------------------------------------------------------------------

def cmd_trainer_start(args: argparse.Namespace) -> int:
    from .trainer import agent

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    creds = credentials.load_user()
    server = args.server or (creds.server if creds else None)
    if server is None:
        print("not logged in. Run: plasmon login --server http://<host>:7117", file=sys.stderr)
        return 1
    ident = agent.machine_key_or_create(machine_key_path())
    a = agent.Agent(server, creds.token if creds and creds.server == server else None, ident, args.name or agent.default_name(), device=args.device, max_hours=args.max_hours)
    try:
        a.run()
    except KeyboardInterrupt:
        a.stop()
        print("\nstopped")
    return 0


# ----- fleet and ledger ------------------------------------------------------------------

def cmd_fleet(args: argparse.Namespace) -> int:
    client = _client(args)
    machines = client.fleet(status=args.status)
    rows = []
    for m in machines:
        met = m.get("metrics") or {}
        gpu = (m.get("hardware") or {}).get("gpu") or {}
        rows.append([
            m["name"], m.get("owner") or "", m["status"], gpu.get("name", "none" if gpu.get("kind") in (None, "none") else gpu.get("kind")),
            f"{met.get('gpu_pct', '')}", f"{met.get('cpu_pct', '')}", f"{met.get('ram_pct', '')}",
            f"{m['current_job_id'] or ''} {('r' + str(m['current_round'])) if m['current_round'] is not None else ''}".strip(),
            f"{m['honesty']:.2f}", m["last_seen_at"][11:19] if m.get("last_seen_at") else "never",
        ])
    _print(args, machines, _fmt_table(rows, ["machine", "owner", "status", "gpu", "gpu%", "cpu%", "ram%", "job / round", "honesty", "seen"]) if rows else "no machines")
    return 0


def cmd_ledger_verify(args: argparse.Namespace) -> int:
    out = _client(args).ledger_verify()
    _print(args, out, f"ledger ok: {out['ok']}  entries: {out['entries']}" + (f"  problem: {out['problem']}" if out["problem"] else ""))
    return 0 if out["ok"] else 1


def cmd_bench(args: argparse.Namespace) -> int:
    from .core import jobspec
    from .train import data, simulate

    spec = jobspec.load(args.job) if args.job else jobspec.loads(
        "name: bench\nmodel: {arch: mnist_cnn}\ndataset: {source: builtin://mnist}\n"
        "recipe: {inner_steps: 50, inner_optimizer: {lr: 2.0e-3}}\n"
    )
    train, test = data.load_mnist()
    train = data.Shard(train.x[: args.train_samples], train.y[: args.train_samples])
    test = data.Shard(test.x[:2000], test.y[:2000])
    shards = data.split_shards(train, spec.dataset.shard_size, seed=1)
    sim = simulate.run(spec, shards, test, trainers=args.trainers, rounds=args.rounds)
    steps = args.rounds * spec.recipe.inner_steps
    _, base_acc = simulate.baseline(spec, train, test, steps=steps)
    print(f"{'round':>5} {'eval loss':>9} {'eval acc':>8} {'frame bytes':>11} {'dense bytes':>11}")
    for r in sim.rounds:
        print(f"{r.round:>5} {r.eval_loss:>9.4f} {r.eval_acc:>8.4f} {r.frame_bytes:>11,} {r.dense_bytes:>11,}")
    pct = 100 * sim.total_frame_bytes / sim.total_dense_bytes
    print(f"diloco x{args.trainers}: {sim.final_acc:.4f}   single worker, {steps} steps: {base_acc:.4f}")
    print(f"traffic: {sim.total_frame_bytes:,} B sent vs {sim.total_dense_bytes:,} B dense ({pct:.1f} %)")
    return 0


# ----- parser ----------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="plasmon", description="plasmon engine")
    parser.add_argument("--version", action="version", version=f"plasmon {__version__}")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--server", help="coordinator URL (default: the one you logged in to)")
    # The same two options are accepted after a subcommand. SUPPRESS keeps a leaf parser
    # from overwriting a value given before the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    common.add_argument("--server", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("init", help="create this machine's Ed25519 key", parents=[common])
    p.add_argument("--force", action="store_true")
    p.set_defaults(handler=cmd_init)

    p = sub.add_parser("login", help="log in to a coordinator (device code, or --email)", parents=[common])
    p.add_argument("--email")
    p.add_argument("--password")
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(handler=cmd_login)
    sub.add_parser("logout", parents=[common]).set_defaults(handler=cmd_logout)
    sub.add_parser("whoami", parents=[common]).set_defaults(handler=cmd_whoami)

    server = sub.add_parser("server", help="run and manage a coordinator").add_subparsers(dest="server_command")
    p = server.add_parser("init", help="write plasmon-server.yaml", parents=[common])
    p.add_argument("--mode", choices=["home", "private", "public"], default="home")
    p.add_argument("--port", type=int, default=7117)
    p.add_argument("--org", default="home")
    p.add_argument("--public-url")
    p.add_argument("--config")
    p.set_defaults(handler=cmd_server_init)
    p = server.add_parser("start", help="start the coordinator", parents=[common])
    p.add_argument("--config")
    p.set_defaults(handler=cmd_server_start)
    p = server.add_parser("bootstrap", help="create the owner account on an empty server", parents=[common])
    p.add_argument("--owner", required=True, help="owner email")
    p.add_argument("--password")
    p.add_argument("--name")
    p.add_argument("--config")
    p.set_defaults(handler=cmd_server_bootstrap)
    server.add_parser("status", help="coordinator health (operator role)", parents=[common]).set_defaults(handler=cmd_server_status)

    job = sub.add_parser("job", help="submit and follow jobs").add_subparsers(dest="job_command")
    p = job.add_parser("submit", parents=[common])
    p.add_argument("file")
    p.set_defaults(handler=cmd_job_submit)
    p = job.add_parser("list", parents=[common])
    p.add_argument("--all", action="store_true", help="every job in the org (operator role)")
    p.set_defaults(handler=cmd_job_list)
    p = job.add_parser("status", parents=[common])
    p.add_argument("id")
    p.set_defaults(handler=cmd_job_status)
    p = job.add_parser("watch", parents=[common])
    p.add_argument("id")
    p.add_argument("--interval", type=float, default=2.0)
    p.set_defaults(handler=cmd_job_watch)
    p = job.add_parser("download", parents=[common])
    p.add_argument("id")
    p.add_argument("-o", "--output")
    p.set_defaults(handler=cmd_job_download)
    p = job.add_parser("cancel", parents=[common])
    p.add_argument("id")
    p.set_defaults(handler=cmd_job_cancel)

    trainer = sub.add_parser("trainer", help="offer this machine").add_subparsers(dest="trainer_command")
    p = trainer.add_parser("start", parents=[common])
    p.add_argument("--name", help="machine name shown in the fleet (default: hostname)")
    p.add_argument("--device", choices=["any", "cuda", "mps", "cpu"], default="any")
    p.add_argument("--max-hours", type=float)
    p.set_defaults(handler=cmd_trainer_start)

    p = sub.add_parser("fleet", help="machines you can see", parents=[common])
    p.add_argument("--status")
    p.set_defaults(handler=cmd_fleet)

    ledger = sub.add_parser("ledger").add_subparsers(dest="ledger_command")
    ledger.add_parser("verify", parents=[common]).set_defaults(handler=cmd_ledger_verify)

    p = sub.add_parser("bench-diloco", help="simulate N trainers in one process and compare with one worker", parents=[common])
    p.add_argument("--job")
    p.add_argument("--trainers", type=int, default=2)
    p.add_argument("--rounds", type=int, default=6)
    p.add_argument("--train-samples", type=int, default=12000)
    p.set_defaults(handler=cmd_bench)
    return parser


def main(argv: Sequence[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler: Handler | None = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    try:
        return handler(args)
    except ApiError as e:
        print(f"error: {e.message}", file=sys.stderr)
        return 1
