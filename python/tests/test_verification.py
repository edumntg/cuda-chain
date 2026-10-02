"""Seeded cheaters against a live coordinator: random Δ, copied Δ, wrong shard, NaN."""

from __future__ import annotations

import threading
import time

import pytest
import torch
from plasmon import jobs
from plasmon.client import Client
from plasmon.core import jobspec
from plasmon.core.identity import Identity
from plasmon.train import diloco
from plasmon.trainer.agent import Agent
from plasmon.validator import scoring

pytestmark = pytest.mark.timeout(420)


class RandomAgent(Agent):
    """Never trains: sends noise shaped like an update."""

    def train_round(self, spec, theta, x, y, job_id, rnd, assignment):
        gen = torch.Generator().manual_seed(1000 + rnd)
        delta = {k: torch.randn(v.shape, generator=gen) * 0.05 for k, v in theta.items()}
        return diloco.RoundResult(delta, 2.3, 2.3, spec.recipe.inner_steps * spec.recipe.batch_size, spec.recipe.inner_steps)


class MislabeledAgent(Agent):
    """Trains on its shard with every label shifted: a poisoned update."""

    def train_round(self, spec, theta, x, y, job_id, rnd, assignment):
        return super().train_round(spec, theta, x, (y + 1) % 10, job_id, rnd, assignment)


class NanAgent(Agent):
    def train_round(self, spec, theta, x, y, job_id, rnd, assignment):
        delta = {k: torch.full_like(v, float("nan")) for k, v in theta.items()}
        return diloco.RoundResult(delta, 1.0, 1.0, 64, 1)


class CopyAgent(Agent):
    """Reuses the honest trainer's revealed Δ: a free rider with a plausible update."""

    def __init__(self, *args, source: Agent, **kwargs):
        super().__init__(*args, **kwargs)
        self.source = source

    def train_round(self, spec, theta, x, y, job_id, rnd, assignment):
        for _ in range(600):  # wait for the honest trainer's result of this round
            got = getattr(self.source, "last_delta", None)
            if got is not None and got[0] == rnd:
                return diloco.RoundResult({k: v.clone() for k, v in got[1].items()}, 1.0, 0.5, spec.recipe.inner_steps * spec.recipe.batch_size, spec.recipe.inner_steps)
            time.sleep(0.05)
        return super().train_round(spec, theta, x, y, job_id, rnd, assignment)


class HonestAgent(Agent):
    def after_reveal(self, job_id, rnd, result):
        self.last_delta = (rnd, {k: v.clone() for k, v in result.delta.items()})


def _spec(dataset_dir, name, trainers, rounds, timeout=90):
    return jobspec.loads(
        f"""
name: {name}
model: {{arch: mnist_cnn}}
dataset: {{source: "{dataset_dir.as_posix()}", shard_size: 500, eval_fraction: 0.1}}
recipe: {{inner_steps: 25, batch_size: 64, inner_optimizer: {{lr: 2.0e-3}}, compression: {{topk: 0.1}}}}
requirements: {{min_trainers: {trainers}, max_trainers: {trainers}, round_timeout_s: {timeout}}}
budget: {{rounds: {rounds}}}
"""
    )


def _run(server, owner, agents, job, timeout=300):
    threads = [threading.Thread(target=a.run, daemon=True) for a in agents]
    for t in threads:
        t.start()
    try:
        return owner.wait_job(job["id"], timeout_s=timeout, poll_s=1.0)
    finally:
        for a in agents:
            a.stop()
        for t in threads:
            t.join(timeout=30)


def test_random_nan_and_honest(server, dataset_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("PLASMON_CACHE_DIR", str(tmp_path / "cache"))
    owner = Client(server)
    owner.register("verify@example.com", "verify-password")
    owner.login("verify@example.com", "verify-password")
    job = jobs.submit(owner, _spec(dataset_dir, "verify-random", trainers=3, rounds=5), progress=lambda s: None)
    honest = HonestAgent(server, owner.token, Identity.generate(), name="honest", device="cpu")
    noisy = RandomAgent(server, owner.token, Identity.generate(), name="noisy", device="cpu")
    nan = NanAgent(server, owner.token, Identity.generate(), name="nan", device="cpu")
    for i, a in enumerate((honest, noisy, nan)):
        a.machine_creds_path = tmp_path / f"m{i}.toml"
    final = _run(server, owner, [honest, noisy, nan], job)
    assert final["status"] == "completed", final
    updates = owner.job_updates(job["id"])
    by = {}
    for u in updates:
        by.setdefault(u["machine"], []).append(u)
    assert all(u["status"] == "accepted" and u["score"] > 0 for u in by["honest"]), by["honest"]
    assert all(u["status"] == "rejected" for u in by["nan"]) and "non-finite" in by["nan"][0]["reject_reason"]
    # a lucky noise vector can lower the loss once; over the job it earns almost nothing
    noisy_score = sum(u["score"] or 0 for u in by["noisy"])
    honest_score = sum(u["score"] or 0 for u in by["honest"])
    assert noisy_score < 0.2 * honest_score, (noisy_score, honest_score)
    rejected_noisy = [u for u in by["noisy"] if u["status"] == "rejected"]
    assert rejected_noisy, by["noisy"]
    assert any("worse" in u["reject_reason"] or "norm" in u["reject_reason"] or "honesty" in u["reject_reason"] for u in rejected_noisy)
    last_round = max(u["round"] for u in by["noisy"])
    assert all(u["status"] == "rejected" for u in by["noisy"] if u["round"] == last_round), by["noisy"]
    fleet = {m["name"]: m for m in owner.fleet()}
    assert fleet["honest"]["honesty"] > 0.9, fleet["honest"]
    assert fleet["noisy"]["honesty"] < 0.5 and fleet["nan"]["honesty"] < 0.5
    assert final["rounds"][-1]["accepted"] == 1  # only the honest update entered θ in the last round
    ledger = owner.ledger(job=job["id"])
    round_entries = [e for e in ledger if e["kind"] == "round"]
    assert round_entries and all(len(e["body"]["rejected"]) >= 1 for e in round_entries)


def test_copier_and_poisoner(server, dataset_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("PLASMON_CACHE_DIR", str(tmp_path / "cache"))
    owner = Client(server)
    owner.login("verify@example.com", "verify-password")
    job = jobs.submit(owner, _spec(dataset_dir, "verify-copy", trainers=3, rounds=5), progress=lambda s: None)
    honest = HonestAgent(server, owner.token, Identity.generate(), name="honest2", device="cpu")
    copier = CopyAgent(server, owner.token, Identity.generate(), name="copier", device="cpu", source=honest)
    poison = MislabeledAgent(server, owner.token, Identity.generate(), name="poison", device="cpu")
    for i, a in enumerate((honest, copier, poison)):
        a.machine_creds_path = tmp_path / f"c{i}.toml"
    final = _run(server, owner, [honest, copier, poison], job, timeout=400)
    assert final["status"] == "completed", final
    updates = owner.job_updates(job["id"])
    by = {}
    for u in updates:
        by.setdefault(u["machine"], []).append(u)
    # the copier can only copy what was revealed, so its commit is later: rejected as a duplicate
    assert all(u["status"] == "rejected" for u in by["copier"]), by["copier"]
    assert any("duplicate" in u["reject_reason"] for u in by["copier"]), by["copier"]
    # shifted labels make the model worse on the assigned shard; in round 0 the model is
    # still random and the loss can stay flat, so the check starts at round 1
    assert all(u["status"] == "rejected" for u in by["poison"] if u["round"] >= 1), by["poison"]
    assert any("worse" in u["reject_reason"] or "honesty" in u["reject_reason"] for u in by["poison"])
    assert sum(u["score"] or 0 for u in by["poison"]) < 0.1 * sum(u["score"] or 0 for u in by["honest2"])
    assert all(u["status"] == "accepted" for u in by["honest2"]), by["honest2"]
    fleet = {m["name"]: m for m in owner.fleet()}
    assert fleet["honest2"]["honesty"] > 0.9 > fleet["copier"]["honesty"]
    assert fleet["poison"]["honesty"] < 0.5
    assert final["eval_acc"] > 0.8


def test_scorer_unit():
    import numpy as np
    from plasmon.train import data, models

    spec = jobspec.loads("name: s\nmodel: {arch: mlp}\ndataset: {source: builtin://mnist}\n")
    theta = models.init_weights("mlp", {}, 0)
    rng = np.random.default_rng(0)
    shards = {i: data.Shard((rng.random((64, 28, 28)) * 255).astype(np.uint8), rng.integers(0, 10, 64).astype(np.uint8)).to_bytes() for i in range(2)}
    scorer = scoring.Scorer(scoring.ScoringConfig(), spec, theta, shards, random_shard=1)
    zero = {k: torch.zeros_like(v) for k, v in theta.items()}
    assert scorer.cheap_checks(zero, None) == "empty update"
    bad_shape = {k: torch.zeros(3) for k in theta}
    assert "shape" in scorer.cheap_checks(bad_shape, None)
    big = {k: torch.ones_like(v) * 100 for k, v in theta.items()}
    assert "exceeds" in scorer.cheap_checks(big, median_norm=1.0)
    small = {k: torch.randn_like(v) * 1e-4 for k, v in theta.items()}
    verdict = scorer.judge(small, 0, None, honesty=1.0, sampled=True)
    assert verdict.gain_assigned is not None and verdict.signal in (0, 1)
    floor = scorer.judge(small, 0, None, honesty=0.1, sampled=True)
    assert not floor.accepted and "honesty" in floor.reason
    assert scoring.update_honesty(1.0, 0, 0.25) == 0.75 and scoring.update_honesty(0.5, None, 0.25) == 0.5
