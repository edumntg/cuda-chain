"""The trainer reports `training` the moment a round starts, not at the next interval."""

import numpy as np
import torch
from plasmon.core import jobspec
from plasmon.core.identity import Identity
from plasmon.train import data, models, weights
from plasmon.trainer.agent import Agent


class FakeClient:
    def __init__(self, blobs):
        self.blobs = blobs
        self.heartbeats = []
        self.commits = []

    def heartbeat(self, body):
        self.heartbeats.append(dict(body))
        return {"interval": 10, "idle_interval": 3, "commands": []}

    def get_blob(self, blob_id):
        return self.blobs[blob_id]

    def commit(self, job_id, rnd, blob, signature):
        self.commits.append((job_id, rnd, blob))
        return {"status": "committed"}

    def put_blob(self, data, kind=""):
        return "x" * 64

    def reveal(self, job_id, rnd, blob):
        return {"status": "revealed"}


def test_run_assignment_sends_training_heartbeat_first(tmp_path, monkeypatch):
    monkeypatch.setenv("PLASMON_CACHE_DIR", str(tmp_path / "cache"))
    spec = jobspec.loads("name: hb\nmodel: {arch: mlp}\ndataset: {source: builtin://mnist}\nrecipe: {inner_steps: 2, batch_size: 8}\n")
    theta = models.init_weights("mlp", {}, 0)
    theta_bytes = weights.to_bytes(theta)
    rng = np.random.default_rng(0)
    shard = data.Shard((rng.random((16, 28, 28)) * 255).astype(np.uint8), rng.integers(0, 10, 16).astype(np.uint8))
    client = FakeClient({"t" * 64: theta_bytes, "s" * 64: shard.to_bytes()})
    agent = Agent("http://test", None, Identity.generate(), name="hb-pc", device="cpu")
    agent.client = client
    agent.run_assignment({"job_id": "job_x", "round": 3, "theta": "t" * 64, "shard": {"index": 0, "blob": "s" * 64, "n": 16}, "spec": spec.model_dump(mode="json"), "deadline_at": "2030-01-01T00:00:00"})
    assert client.heartbeats, "no heartbeat was sent at the start of the round"
    first = client.heartbeats[0]
    assert first["status"] == "training" and first["job_id"] == "job_x" and first["round"] == 3
    assert client.commits and client.commits[0][1] == 3
    assert torch.is_tensor(theta["net.1.weight"])
