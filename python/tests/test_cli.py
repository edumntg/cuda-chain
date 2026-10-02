"""The `python -m plasmon` commands against a live coordinator, as a user would run them."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from plasmon.client import Client
from plasmon.core.identity import Identity
from plasmon.trainer.agent import Agent

pytestmark = pytest.mark.timeout(420)


def run(args: list[str], env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run([sys.executable, "-m", "plasmon", *args], capture_output=True, text=True, env=env, timeout=300)
    if check and proc.returncode != 0:
        raise AssertionError(f"plasmon {' '.join(args)} failed ({proc.returncode})\nstdout: {proc.stdout}\nstderr: {proc.stderr}")
    return proc


def test_cli_end_to_end(server, dataset_dir, tmp_path):
    env = {**os.environ, "PLASMON_CONFIG_DIR": str(tmp_path / "config"), "PLASMON_CACHE_DIR": str(tmp_path / "cache"), "PLASMON_DATA_DIR": str(tmp_path / "data")}
    assert "plasmon 0.1.0" in run(["--version"], env).stdout

    # bootstrap works on a fresh, separate server database
    cfg = tmp_path / "other-server.yaml"
    out = run(["--json", "server", "init", "--mode", "private", "--port", "7999", "--config", str(cfg)], env).stdout
    assert json.loads(out)["config"] == str(cfg)
    out = json.loads(run(["--json", "server", "bootstrap", "--owner", "boss@acme.test", "--password", "secret-pass", "--config", str(cfg)], env).stdout)
    assert out["email"] == "boss@acme.test"
    assert run(["server", "bootstrap", "--owner", "x@acme.test", "--config", str(cfg)], env, check=False).returncode == 1

    # the live server: register through the API, then the whole CLI flow
    api = Client(server)
    api.register("cli@example.com", "cli-password", "CLI User")
    out = run(["login", "--server", server, "--email", "cli@example.com", "--password", "cli-password"], env).stdout
    assert "logged in to" in out
    who = json.loads(run(["--json", "whoami"], env).stdout)
    assert who["user"] == "cli@example.com" and who["server"] == server

    init = json.loads(run(["--json", "init"], env).stdout)
    assert len(init["node_id"]) == 64

    job_yaml = tmp_path / "job.yaml"
    job_yaml.write_text(
        f"""
name: cli-mnist
model: {{arch: mlp}}
dataset: {{source: "{Path(dataset_dir).as_posix()}", shard_size: 1000}}
recipe: {{inner_steps: 15, inner_optimizer: {{lr: 2.0e-3}}}}
requirements: {{min_trainers: 1, max_trainers: 1, round_timeout_s: 60}}
budget: {{rounds: 2}}
"""
    )
    job = json.loads(run(["--json", "job", "submit", str(job_yaml)], env).stdout)
    assert job["name"] == "cli-mnist" and job["status"] == "running"
    listed = json.loads(run(["--json", "job", "list"], env).stdout)
    assert [j["id"] for j in listed] == [job["id"]]

    # one trainer in-process (the CLI's `trainer start` runs the same Agent class)
    api.login("cli@example.com", "cli-password")
    agent = Agent(server, api.token, Identity.generate(), name="cli-pc", device="cpu")
    agent.machine_creds_path = tmp_path / "machine.toml"
    thread = threading.Thread(target=agent.run, daemon=True)
    thread.start()
    try:
        watch = run(["job", "watch", job["id"], "--interval", "0.5"], env)
    finally:
        agent.stop()
        thread.join(timeout=30)
    assert "round    0" in watch.stdout and "job completed" in watch.stdout

    status = run(["job", "status", job["id"]], env).stdout
    assert "completed" in status and "round 2/2" in status
    fleet = run(["fleet"], env).stdout
    assert "cli-pc" in fleet
    assert "ledger ok: True" in run(["ledger", "verify"], env).stdout
    out_file = tmp_path / "model.safetensors"
    run(["job", "download", job["id"], "-o", str(out_file)], env)
    assert out_file.stat().st_size > 1000

    # server status needs the operator role: allowed when this account is the owner
    role = json.loads(run(["--json", "whoami"], env).stdout)["role"]
    assert run(["server", "status"], env, check=False).returncode == (0 if role == "owner" else 1)
    run(["logout"], env)
    assert "not logged in" in run(["whoami"], env).stdout
