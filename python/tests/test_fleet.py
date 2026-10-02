"""Fleet control, machine logs, users, invites, audit, policy, metrics and the admin pages."""

from __future__ import annotations

import threading
import time

import httpx
import pytest
from plasmon.client import ApiError, Client
from plasmon.core.identity import Identity
from plasmon.trainer.agent import Agent

pytestmark = pytest.mark.timeout(300)


@pytest.fixture(scope="module")
def admin(server):
    c = Client(server)
    c.register("admin@acme.test", "admin-password", "Admin")
    c.login("admin@acme.test", "admin-password")
    assert c.me()["user"]["role"] == "owner"
    return c


@pytest.fixture(scope="module")
def machine(server, admin, tmp_path_factory):
    agent = Agent(server, admin.token, Identity.generate(), name="lab-pc", device="cpu")
    agent.machine_creds_path = tmp_path_factory.mktemp("m") / "machine.toml"
    thread = threading.Thread(target=agent.run, daemon=True)
    thread.start()
    for _ in range(100):
        fleet = admin.fleet()
        if fleet and fleet[0]["status"] == "idle":
            break
        time.sleep(0.2)
    yield agent, fleet[0]["node_id"]
    agent.stop()
    thread.join(timeout=20)


def test_pause_drain_resume_and_logs(server, admin, machine):
    agent, node = machine
    out = admin.post(f"/v1/fleet/{node}/pause", {"reason": "test"})
    assert out["paused_by_admin"] is True
    for _ in range(50):
        if agent.paused:
            break
        time.sleep(0.2)
    assert agent.paused
    assert admin.machine(node)["status"] in ("paused", "idle")
    admin.post(f"/v1/fleet/{node}/resume")
    for _ in range(50):
        if not agent.paused:
            break
        time.sleep(0.2)
    assert not agent.paused
    admin.post(f"/v1/fleet/{node}/tags", {"tags": ["lab", "gpu-none"]})
    assert admin.machine(node)["tags"] == ["gpu-none", "lab"]
    logs = []
    for _ in range(50):  # the agent ships its log lines with the next heartbeat
        logs = admin.get(f"/v1/fleet/{node}/logs", limit=50)
        if any("paused" in line["message"] for line in logs):
            break
        time.sleep(0.3)
    assert any("paused" in line["message"] for line in logs), logs
    for _ in range(50):
        if admin.get(f"/v1/fleet/{node}/logs", grep="resumed"):
            break
        time.sleep(0.3)
    assert admin.get(f"/v1/fleet/{node}/logs", grep="resumed")
    audit = admin.get("/v1/audit")
    assert {a["action"] for a in audit} >= {"fleet.pause", "fleet.resume", "fleet.tags", "machine.register"}


def test_users_invites_roles(server, admin):
    inv = admin.post("/v1/users/invite", {"email": "ops@acme.test", "role": "operator"})
    assert inv["url"].endswith(f"/register?invite={inv['code']}")
    ops = Client(server)
    with pytest.raises(ApiError):
        ops.register("other@acme.test", "operator-pass", invite=inv["code"]) if False else ops.post("/v1/auth/register", {"email": "other@acme.test", "password": "operator-pass", "invite": inv["code"]})
    ops.post("/v1/auth/register", {"email": "ops@acme.test", "password": "operator-pass", "invite": inv["code"]})
    ops.login("ops@acme.test", "operator-pass")
    assert ops.me()["user"]["role"] == "operator"
    assert admin.get("/v1/users/invites") == []  # used
    users = admin.get("/v1/users")
    ops_id = next(u["id"] for u in users if u["email"] == "ops@acme.test")
    with pytest.raises(ApiError):
        ops.post(f"/v1/users/{ops_id}/role", {"role": "admin"})  # operators cannot manage users
    assert admin.post(f"/v1/users/{ops_id}/role", {"role": "viewer"})["role"] == "viewer"
    assert ops.me()["user"]["role"] == "viewer"  # existing token follows the role
    admin.post(f"/v1/users/{ops_id}/disable", {"disabled": True})
    with pytest.raises(ApiError):
        ops.me()
    admin.post(f"/v1/users/{ops_id}/disable", {"disabled": False})
    ops.login("ops@acme.test", "operator-pass")
    assert ops.me()["user"]["role"] == "viewer"


def test_policy_round_trip(server, admin, machine):
    agent, node = machine
    new = {"windows": [{"days": ["mon", "tue", "wed", "thu", "fri"], "start": "19:00", "end": "08:00"}], "pause_on_battery": False, "drain_at_window_end": True}
    out = admin.request("PUT", "/v1/policy", json=new)
    assert out["windows"][0]["start"] == "19:00"
    for _ in range(50):
        if agent.policy.windows:
            break
        time.sleep(0.2)
    assert agent.policy.windows[0].end == "08:00"
    admin.request("PUT", "/v1/policy", json={"windows": [], "pause_on_battery": True, "drain_at_window_end": True})


def test_metrics_and_admin_pages(server, admin, machine):
    text = httpx.get(f"{server}/v1/metrics").text
    assert 'plasmon_machines{status="idle"}' in text and "plasmon_ledger_entries" in text
    with httpx.Client(base_url=server, follow_redirects=False, timeout=10) as web:
        r = web.post("/login", data={"email": "admin@acme.test", "password": "admin-password", "next": "/"})
        web.cookies.update(r.cookies)
        for path in ("/users", "/settings", f"/machine/{machine[1]}"):
            r = web.get(path)
            assert r.status_code == 200, (path, r.text[:200])
        r = web.post("/users/invite", data={"email": "", "role": "member"})
        assert r.status_code == 303 and "result=invite:" in r.headers["location"]
        r = web.post("/settings/policy", data={"windows_text": "weekends 00:00-23:59", "pause_on_battery": "on"})
        assert r.headers["location"] == "/settings?result=saved"
        assert admin.get("/v1/policy")["windows"][0]["days"] == ["sat", "sun"]
        r = web.post(f"/machine/{machine[1]}/pause")
        assert r.status_code == 303
        assert admin.machine(machine[1])["paused_by_admin"] is True
        web.post(f"/machine/{machine[1]}/resume")
        assert admin.machine(machine[1])["paused_by_admin"] is False
        admin.request("PUT", "/v1/policy", json={"windows": [], "pause_on_battery": True, "drain_at_window_end": True})
