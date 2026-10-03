"""A round waits for the other idle machines before it closes, so a fast machine does not take
every round alone. Two trainers, one slow, min_trainers 1: both must be in every round."""

from __future__ import annotations

import threading
import time

from plasmon import jobs
from plasmon.client import Client
from plasmon.core import jobspec
from plasmon.core.identity import Identity
from plasmon.trainer.agent import Agent


class SlowAgent(Agent):
    def train_round(self, *args, **kwargs):
        time.sleep(2.0)
        return super().train_round(*args, **kwargs)


def test_round_waits_for_the_slow_trainer(server, dataset_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("PLASMON_CACHE_DIR", str(tmp_path / "cache"))
    owner = Client(server)
    owner.register("gather@example.com", "gather-password")
    owner.login("gather@example.com", "gather-password")
    spec = jobspec.loads(
        f"""
name: gather
model: {{arch: mlp}}
dataset: {{source: "{dataset_dir.as_posix()}", shard_size: 1000}}
recipe: {{inner_steps: 5}}
requirements: {{min_trainers: 1, max_trainers: 4, round_timeout_s: 60}}
budget: {{rounds: 3}}
"""
    )
    fast = Agent(server, owner.token, Identity.generate(), name="fast", device="cpu")
    slow = SlowAgent(server, owner.token, Identity.generate(), name="slow", device="cpu")
    fast.machine_creds_path = tmp_path / "fast.toml"
    slow.machine_creds_path = tmp_path / "slow.toml"
    threads = [threading.Thread(target=a.run, daemon=True) for a in (fast, slow)]
    for t in threads:
        t.start()
    time.sleep(2)  # both enrolled and idle before the job exists
    job = jobs.submit(owner, spec, progress=lambda s: None)
    try:
        final = owner.wait_job(job["id"], timeout_s=120)
    finally:
        fast.stop()
        slow.stop()
        for t in threads:
            t.join(timeout=20)
    assert final["status"] == "completed", final
    closed = [r for r in final["rounds"] if r["status"] == "closed"]
    assert len(closed) == 3 and all(r["accepted"] == 2 for r in closed), [(r["index"], r["accepted"]) for r in closed]
    # the two trainers of a round never train the same shard
    for r in closed:
        shards = [u["shard"] for u in owner.job_updates(job["id"], round=r["index"]) if u["status"] == "accepted"]
        assert len(shards) == 2 and shards[0] != shards[1], shards
