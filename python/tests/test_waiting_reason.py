"""A running job with no trainer says why: no machine, none idle, requirements not met, or a
machine still holding an update. A failed job must not keep a machine busy."""

from __future__ import annotations

import httpx
from plasmon import jobs
from plasmon.client import Client
from plasmon.core import jobspec
from plasmon.core.identity import Identity
from sqlalchemy import create_engine, text


def _spec(name: str, dataset_dir, device: str) -> jobspec.JobSpec:
    return jobspec.loads(
        f"""
name: {name}
model: {{arch: mlp}}
dataset: {{source: "{dataset_dir.as_posix()}", shard_size: 1000}}
recipe: {{inner_steps: 5}}
requirements: {{device: {device}, min_trainers: 1, max_trainers: 2, round_timeout_s: 60}}
budget: {{rounds: 2}}
"""
    )


def test_waiting_reason_and_busy_scope(server, dataset_dir, monkeypatch, tmp_path):
    monkeypatch.setenv("PLASMON_CACHE_DIR", str(tmp_path / "cache"))
    owner = Client(server)
    owner.register("why@example.com", "why-password")
    owner.login("why@example.com", "why-password")
    uid = owner.me()["user"]["id"]

    needs_gpu = jobs.submit(owner, _spec("needs-gpu", dataset_dir, "cuda"), progress=lambda s: None)
    assert owner.job(needs_gpu["id"])["waiting_reason"].startswith("No machine is online")

    ident = Identity.generate()
    out = owner.register_machine({"node_id": ident.node_id, "name": "cpu-box", "hardware": {"os": "Windows 11", "gpu": {"kind": "none"}}, "versions": {}, "signature": ident.sign({"node_id": ident.node_id, "user": uid})})
    machine = Client(server, out["machine_token"])
    idle = {"status": "idle", "status_detail": "", "job_id": None, "round": None, "metrics": {}, "logs": []}
    assert machine.heartbeat(idle)["assignment"] is None
    reason = owner.job(needs_gpu["id"])["waiting_reason"]
    assert reason == "1 free machine does not meet the job requirements: device cuda", reason
    assert any(j["id"] == needs_gpu["id"] and j["waiting_reason"] == reason for j in owner.jobs())

    machine.heartbeat({**idle, "status": "paused", "status_detail": "paused by owner"})
    assert owner.job(needs_gpu["id"])["waiting_reason"] == "1 machine online but none is free: 1 paused"

    any_device = jobs.submit(owner, _spec("any-device", dataset_dir, "any"), progress=lambda s: None)
    assigned = machine.heartbeat(idle)["assignment"]
    assert assigned is not None and assigned["job_id"] == any_device["id"]
    detail = owner.job(any_device["id"])
    assert detail["waiting_reason"] is None
    assert detail["trainers"] == [{"node": ident.node_id, "name": "cpu-box", "round": 0, "status": "assigned", "current": True}]
    # the machine holds an update now, so a third job explains that instead of the requirements
    third = jobs.submit(owner, _spec("third", dataset_dir, "any"), progress=lambda s: None)
    assert owner.job(third["id"])["waiting_reason"] == "1 machine online but none is free: 1 busy with another round"
    # a machine between rounds reports `training` and asks with ready=true; the reply carries its job's state
    reply = machine.heartbeat({**idle, "status": "training", "job_id": any_device["id"], "round": 0, "ready": True})
    assert reply["assignment"] is None and reply["job"] == {"status": "running", "round": 0}

    # a job that failed mid-round must not keep its trainer busy for ever
    url = owner.server_status()["db"]["url"]
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("UPDATE jobs SET status = 'failed' WHERE id = :id"), {"id": any_device["id"]})
    engine.dispose()
    assigned = machine.heartbeat(idle)["assignment"]
    assert assigned is not None and assigned["job_id"] == third["id"]
    assert owner.job(third["id"])["waiting_reason"] is None

    # a heartbeat may carry fresh hardware: a GPU driver installed after enrolment shows up
    machine.heartbeat({**idle, "status": "training", "job_id": third["id"], "round": 0, "hardware": {"os": "Windows 11", "gpu": {"kind": "cuda", "name": "NVIDIA GeForce RTX 4070", "vram_gb": 12}}})
    assert owner.fleet()[0]["hardware"]["gpu"]["kind"] == "cuda"

    # the web pages show the same sentence: job page state card, overview job cards
    with httpx.Client(base_url=server, follow_redirects=False, timeout=30) as web:
        r = web.post("/login", data={"email": "why@example.com", "password": "why-password", "next": "/"})
        web.cookies.update(r.cookies)
        expected = owner.job(needs_gpu["id"])["waiting_reason"]
        assert expected == "1 machine online but none is free: 1 busy with another round"
        page = web.get(f"/jobs/{needs_gpu['id']}")
        assert page.status_code == 200 and expected in page.text
        overview = web.get("/partials/overview")
        assert overview.status_code == 200 and expected in overview.text
