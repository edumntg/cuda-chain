"""Credits: welcome grants, per-round settlement, fee, export, out-of-credits stop."""

from __future__ import annotations

import socket
import threading
import time

import httpx
import pytest
import uvicorn
from plasmon import credentials, jobs
from plasmon.client import ApiError, Client
from plasmon.coordinator.app import create_app
from plasmon.coordinator.config import AuthConfig, CreditsConfig, PolicyConfig, ServerConfig
from plasmon.core import jobspec
from plasmon.core.identity import Identity
from plasmon.trainer.agent import Agent

pytestmark = pytest.mark.timeout(420)


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def credit_server(tmp_path_factory):
    root = tmp_path_factory.mktemp("credits")
    port = _port()
    cfg = ServerConfig(
        mode="private", host="127.0.0.1", port=port, data_dir=str(root), public_url=f"http://127.0.0.1:{port}",
        auth=AuthConfig(open_registration=True), policy=PolicyConfig(heartbeat_interval_s=2, idle_poll_interval_s=1), tick_interval_s=0.3,
        credits=CreditsConfig(enabled=True, fee_pct=10, grant_on_register=1000),
    )
    srv = uvicorn.Server(uvicorn.Config(create_app(cfg), host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            httpx.get(f"{base}/v1/healthz", timeout=1).raise_for_status()
            break
        except Exception:
            time.sleep(0.1)
    yield base
    srv.should_exit = True


def _spec(dataset_dir, name, price, rounds=2, max_credits=None):
    budget = f"rounds: {rounds}, credits_per_1k_samples: {price}" + (f", max_credits: {max_credits}" if max_credits is not None else "")
    return jobspec.loads(
        f"""
name: {name}
model: {{arch: mlp}}
dataset: {{source: "{dataset_dir.as_posix()}", shard_size: 1000}}
recipe: {{inner_steps: 10, batch_size: 64}}
requirements: {{min_trainers: 1, max_trainers: 1, round_timeout_s: 60}}
budget: {{{budget}}}
"""
    )


def _train(server, token, name, path, job_wait):
    agent = Agent(server, token, Identity.generate(), name=name, device="cpu")
    agent.machine_creds_path = path
    thread = threading.Thread(target=agent.run, daemon=True)
    thread.start()
    try:
        return job_wait()
    finally:
        agent.stop()
        thread.join(timeout=20)


def test_settlement_and_export(credit_server, dataset_dir, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PLASMON_CACHE_DIR", str(tmp_path / "cache"))
    owner = Client(credit_server)
    owner.register("owner@example.com", "owner-password")
    owner.login("owner@example.com", "owner-password")
    lender = Client(credit_server)
    lender.register("lender@example.com", "lender-password")
    lender.login("lender@example.com", "lender-password")
    assert owner.get("/v1/credits/me")["balance"] == 1000  # welcome grant
    assert lender.get("/v1/credits/me")["balance"] == 1000

    with pytest.raises(ApiError) as e:
        jobs.submit(owner, _spec(dataset_dir, "too-expensive", price=100, max_credits=5000), progress=lambda s: None)
    assert e.value.status == 402

    job = jobs.submit(owner, _spec(dataset_dir, "paid", price=100), progress=lambda s: None)
    final = _train(credit_server, lender.token, "lender-pc", tmp_path / "l.toml", lambda: owner.wait_job(job["id"], 120))
    assert final["status"] == "completed"
    # 10 steps × 64 = 640 samples per round → 64 credits per round, 2 rounds
    assert final["credits_spent"] == 128
    assert owner.get("/v1/credits/me")["balance"] == 1000 - 128
    lender_me = lender.get("/v1/credits/me")
    assert lender_me["balance"] == 1000 + 2 * 58  # 64 minus the fee of round(6.4) = 6
    assert {e["kind"] for e in lender_me["entries"]} == {"grant", "earn"}
    balances = {b["email"]: b["balance"] for b in owner.get("/v1/credits/users")}
    assert balances["(fee account)"] == 2 * 6
    assert sum(balances.values()) == 2000  # nothing created or lost in settlement
    board = owner.get("/v1/leaderboard")
    assert board[0]["credits_earned"] == 116
    updates = owner.job_updates(job["id"])
    assert all(u["status"] == "accepted" for u in updates)
    ledger = [e for e in owner.ledger(job=job["id"]) if e["kind"] == "round"]
    assert all(e["body"]["credits_spent"] == 64 for e in ledger)

    csv_text = owner._http.get("/v1/credits/export.csv", params={"since_days": 1}, headers=owner._headers()).text
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("at_utc,user,machine,job,round,kind,amount,memo")
    assert sum(1 for line in lines if ",earn," in line) == 2 and sum(1 for line in lines if ",fee," in line) == 2

    grant = owner.post("/v1/credits/grant", {"email": "lender@example.com", "amount": 50, "memo": "thanks"})
    assert grant["balance"] == 1116 + 50
    with pytest.raises(ApiError):
        lender.post("/v1/credits/grant", {"email": "owner@example.com", "amount": 1})

    # the Python command reads the same API
    monkeypatch.setenv("PLASMON_CONFIG_DIR", str(tmp_path / "cfg"))
    credentials.save_user(credentials.UserCredentials(credit_server, "lender@example.com", lender.token))
    from plasmon.cli import main

    assert main(["credits"]) == 0
    out = capsys.readouterr().out
    assert "balance: 1166 credits" in out and "earn" in out

    with httpx.Client(base_url=credit_server, follow_redirects=False, timeout=10) as web:
        r = web.post("/login", data={"email": "owner@example.com", "password": "owner-password", "next": "/"})
        web.cookies.update(r.cookies)
        page = web.get("/credits")
        assert page.status_code == 200 and "872" in page.text and "fee account" in page.text
        r = web.post("/credits/grant", data={"email": "lender@example.com", "amount": "5", "memo": "form"})
        assert r.headers["location"] == "/credits?result=granted"
        assert lender.get("/v1/credits/me")["balance"] == 1171
        assert "credits earned" in web.get("/leaderboard").text


def test_job_stops_when_credits_run_out(credit_server, dataset_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("PLASMON_CACHE_DIR", str(tmp_path / "cache"))
    poor = Client(credit_server)
    poor.register("poor@example.com", "poor-password")
    poor.login("poor@example.com", "poor-password")
    job = jobs.submit(poor, _spec(dataset_dir, "broke", price=2000, rounds=5), progress=lambda s: None)  # 1,280 per round, balance 1,000
    final = _train(credit_server, poor.token, "poor-pc", tmp_path / "p.toml", lambda: poor.wait_job(job["id"], 120))
    assert final["status"] == "cancelled" and final["status_detail"] == "out of credits", final
    assert final["round"] == 1 and final["credits_spent"] == 1000
    assert poor.get("/v1/credits/me")["balance"] == 900  # paid 1,000, earned 90 % of it back as the only trainer


def test_split_integer_sums_exactly():
    from plasmon.coordinator.credits import split_integer

    assert split_integer(900, [0.3]) == [900]
    assert sum(split_integer(58, [1.7, 2.9, 0.4])) == 58
    assert split_integer(10, [1, 1, 1]) == [4, 3, 3]
    assert split_integer(0, [1, 2]) == [0, 0]
    assert sum(split_integer(7, [0.0, 0.0])) == 7
