"""Webhooks, leaderboard, account page, job form, public mode."""

from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
import uvicorn
from plasmon import jobs
from plasmon.client import ApiError, Client
from plasmon.coordinator.app import create_app
from plasmon.coordinator.config import AuthConfig, PolicyConfig, ServerConfig, WebhookConfig
from plasmon.core import jobspec
from plasmon.core.identity import Identity
from plasmon.trainer.agent import Agent

pytestmark = pytest.mark.timeout(420)


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Receiver(BaseHTTPRequestHandler):
    received: list[dict] = []

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        Receiver.received.append(json.loads(self.rfile.read(length)))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def test_webhooks_leaderboard_account_and_job_form(dataset_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("PLASMON_CACHE_DIR", str(tmp_path / "cache"))
    hook_port = _port()
    hook = HTTPServer(("127.0.0.1", hook_port), Receiver)
    threading.Thread(target=hook.serve_forever, daemon=True).start()
    port = _port()
    cfg = ServerConfig(
        mode="public", host="127.0.0.1", port=port, data_dir=str(tmp_path / "srv"), public_url=f"http://127.0.0.1:{port}",
        auth=AuthConfig(open_registration=True), policy=PolicyConfig(heartbeat_interval_s=2, idle_poll_interval_s=1), tick_interval_s=0.3,
        webhooks=[WebhookConfig(url=f"http://127.0.0.1:{hook_port}/hook"), WebhookConfig(url=f"http://127.0.0.1:{hook_port}/slack", format="slack", events=["job.completed"])],
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
    try:
        owner = Client(base)
        owner.register("owner@example.com", "owner-password")
        owner.login("owner@example.com", "owner-password")
        spec = jobspec.loads(
            f"""
name: hooks
model: {{arch: mlp}}
dataset: {{source: "{dataset_dir.as_posix()}", shard_size: 1000}}
recipe: {{inner_steps: 10}}
requirements: {{min_trainers: 1, max_trainers: 1, round_timeout_s: 60}}
budget: {{rounds: 2}}
"""
        )
        job = jobs.submit(owner, spec, progress=lambda s: None)
        agent = Agent(base, owner.token, Identity.generate(), name="hook-pc", device="cpu")
        agent.machine_creds_path = tmp_path / "m.toml"
        thread = threading.Thread(target=agent.run, daemon=True)
        thread.start()
        try:
            final = owner.wait_job(job["id"], timeout_s=120)
        finally:
            agent.stop()
            thread.join(timeout=20)
        assert final["status"] == "completed"
        for _ in range(50):
            if len(Receiver.received) >= 2:
                break
            time.sleep(0.1)
        kinds = [(r.get("event"), "text" in r) for r in Receiver.received]
        assert ("job.completed", True) in kinds, Receiver.received
        slack = [r for r in Receiver.received if "event" not in r]
        assert slack and "completed" in slack[0]["text"]

        board = owner.get("/v1/leaderboard")
        assert board[0]["name"] == "hook-pc" and board[0]["samples_verified"] > 0

        with httpx.Client(base_url=base, follow_redirects=False, timeout=30) as web:
            r = web.post("/login", data={"email": "owner@example.com", "password": "owner-password", "next": "/"})
            web.cookies.update(r.cookies)
            for path in ("/", "/leaderboard", "/account", "/jobs/new", "/jobs"):
                r = web.get(path)
                assert r.status_code == 200, (path, r.status_code)
                assert "plasmon" in r.text
            assert "hook-pc" in web.get("/leaderboard").text
            # password change through the form, then the old password fails
            r = web.post("/account/password", data={"current": "owner-password", "new": "new-password-123"})
            assert r.headers["location"] == "/account?result=password"
            with pytest.raises(ApiError):
                Client(base).login("owner@example.com", "owner-password")
            Client(base).login("owner@example.com", "new-password-123")
            # revoke the CLI token from the account page
            page = web.get("/account").text
            assert "cli" in page
            tokens = owner.get("/v1/auth/tokens")
            assert len(tokens) >= 2  # the first login and the login with the new password
            for tok in tokens:
                r = web.post(f"/account/tokens/{tok['id']}/revoke")
                assert r.status_code == 303
            with pytest.raises(ApiError):
                owner.me()
            # a job from the browser form, prepared on the server
            yaml_text = f"name: form-job\nmodel: {{arch: mlp}}\ndataset: {{source: \"{dataset_dir.as_posix()}\", shard_size: 1000}}\nrequirements: {{min_trainers: 1}}\nbudget: {{rounds: 1}}\n"
            r = web.post("/jobs/new", data={"yaml_text": yaml_text})
            assert r.status_code == 303 and r.headers["location"].startswith("/jobs/job_"), r.text[:300]
            r = web.post("/jobs/new", data={"yaml_text": "name: bad\nmodel: {arch: nope}\ndataset: {source: builtin://mnist}\n"})
            assert r.status_code == 200 and "arch must be one of" in r.text
    finally:
        srv.should_exit = True
        hook.shutdown()


def test_public_mode_keeps_registration_open(tmp_path):
    from plasmon.cli import main

    cfg_path = tmp_path / "pub.yaml"
    assert main(["server", "init", "--mode", "public", "--config", str(cfg_path)]) == 0
    assert "open_registration: true" in cfg_path.read_text()
    cfg_path2 = tmp_path / "priv.yaml"
    assert main(["server", "init", "--mode", "private", "--config", str(cfg_path2)]) == 0
    assert "open_registration: false" in cfg_path2.read_text()
