"""End to end on one machine: a coordinator, two trainers, one MNIST job.

The test runs the real HTTP server, the real agent loop and the real dashboard pages.
"""

from __future__ import annotations

import threading

import httpx
import pytest
from plasmon import jobs
from plasmon.client import ApiError, Client
from plasmon.core import jobspec
from plasmon.core.identity import Identity
from plasmon.trainer.agent import Agent

pytestmark = pytest.mark.timeout(420)


def test_server_two_trainers_one_job(server, dataset_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("PLASMON_CACHE_DIR", str(tmp_path / "cache"))
    owner = Client(server)
    owner.register("owner@example.com", "owner-password", "Owner")
    out = owner.login("owner@example.com", "owner-password")
    assert out["user"]["role"] == "owner"

    spec = jobspec.loads(
        f"""
name: mnist-e2e
model: {{arch: mnist_cnn}}
dataset: {{source: "{dataset_dir.as_posix()}", shard_size: 500, eval_fraction: 0.1}}
recipe: {{inner_steps: 25, batch_size: 64, inner_optimizer: {{lr: 2.0e-3}}, compression: {{topk: 0.1}}}}
requirements: {{min_trainers: 2, max_trainers: 2, round_timeout_s: 90}}
budget: {{rounds: 4}}
"""
    )
    job = jobs.submit(owner, spec, progress=lambda s: None)
    assert job["status"] == "running" and job["shards"] == 11

    agents = []
    for i in range(2):
        ident = Identity.generate()
        a = Agent(server, owner.token, ident, name=f"pc-{i}", device="cpu")
        a.machine_creds_path = tmp_path / f"machine-{i}.toml"
        agents.append(a)
    threads = [threading.Thread(target=a.run, daemon=True) for a in agents]
    for t in threads:
        t.start()
    try:
        final = owner.wait_job(job["id"], timeout_s=300, poll_s=1.0)
    finally:
        for a in agents:
            a.stop()
        for t in threads:
            t.join(timeout=30)

    assert final["status"] == "completed", final
    assert final["round"] == 4
    closed = [r for r in final["rounds"] if r["status"] == "closed"]
    assert len(closed) == 4 and all(r["accepted"] == 2 for r in closed)
    assert final["eval_acc"] > 0.80, final["eval_acc"]

    updates = owner.job_updates(job["id"])
    assert len(updates) == 8 and all(u["status"] == "accepted" for u in updates)

    fleet = owner.fleet()
    assert sorted(m["name"] for m in fleet) == ["pc-0", "pc-1"]
    assert all(m["rounds_served"] == 4 for m in fleet)

    verify = owner.ledger_verify()
    assert verify["ok"] and verify["entries"] >= 6  # created + 4 rounds + finished

    weights_blob = owner.get_blob(final["theta"])
    assert len(weights_blob) > 1000

    status = owner.server_status()
    assert status["scheduler"]["running"] and status["counts"]["machines"] == 2


def test_dashboard_pages_and_device_flow(server):
    with httpx.Client(base_url=server, follow_redirects=False, timeout=10) as web:
        r = web.get("/")
        assert r.status_code == 303 and r.headers["location"] == "/login"
        r = web.post("/login", data={"email": "owner@example.com", "password": "owner-password", "next": "/"})
        assert r.status_code == 303
        web.cookies.update(r.cookies)
        for path in ["/", "/jobs", "/machine", "/fleet", "/server", "/ledger", "/partials/overview", "/partials/jobs", "/partials/fleet"]:
            r = web.get(path)
            assert r.status_code in (200, 303), (path, r.status_code)
            if r.status_code == 200 and not path.startswith("/partials/"):
                assert "plasmon" in r.text and "<main" in r.text, path
            elif r.status_code == 200:
                assert "<table" in r.text or "focal" in r.text or "card" in r.text, path
        cli = Client(server)
        start = cli.device_start(label="test cli")
        assert start["verification_uri"].endswith("/device")
        assert cli.device_poll(start["device_code"])["status"] == "pending"
        r = web.get(f"/device?code={start['user_code']}")
        assert r.status_code == 200 and start["user_code"] in r.text
        r = web.post("/device", data={"code": start["user_code"].lower()})
        assert r.status_code == 200 and "Done" in r.text
        out = cli.device_poll(start["device_code"])
        assert out["user"]["email"] == "owner@example.com" and cli.token
        assert cli.me()["user"]["role"] == "owner"
        r = web.post("/logout")
        assert r.status_code == 303

    member = Client(server)
    member.register("m@example.com", "member-password")
    member.login("m@example.com", "member-password")
    assert member.me()["user"]["role"] == "member"
    with pytest.raises(ApiError):
        member.server_status()
    assert member.jobs() == []
