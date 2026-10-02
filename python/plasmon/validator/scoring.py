"""Gauntlet-style scoring of one round's updates.

For each revealed update Δ_i from trainer i with assigned shard s_i:

    gain_assigned = L(θ_r; s_i) − L(θ_r − Δ_i; s_i)
    gain_random   = L(θ_r; s_x) − L(θ_r − Δ_i; s_x)      s_x: another shard, chosen per round

An honest update lowers the loss on its own shard. A random Δ does not. A copied Δ is
near-identical to an update committed earlier in the same round, which commit-reveal
makes detectable. Each round contributes one honesty signal per machine:

    signal = 1 if gain_assigned > 0 and the update is not a duplicate, else 0
    honesty ← (1 − α) · honesty + α · signal

`gain_random` is recorded for review. When shards come from one distribution an honest
update helps random data almost as much as its own, so the difference is too noisy to
drive honesty on its own.

Cheap checks first: finite values, tensor names and shapes that match θ, a norm bound.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import torch

from ..core import frame as fr
from ..core.jobspec import JobSpec
from ..train import compression, data, diloco

State = dict[str, torch.Tensor]


@dataclass
class ScoringConfig:
    enabled: bool = True
    sample: float = 1.0  # fraction of updates that get the loss-delta check; cheap checks run on all
    norm_clip: float = 8.0  # reject when ||Δ|| > norm_clip × median ||Δ|| of the round
    min_gain: float = -0.02  # reject when the update makes the assigned-shard loss worse than this
    honesty_alpha: float = 0.25
    honesty_floor: float = 0.4  # below this a machine's updates are not aggregated
    max_eval_samples: int = 2000


@dataclass
class Verdict:
    accepted: bool
    reason: str = ""
    score: float | None = None
    gain_assigned: float | None = None
    gain_random: float | None = None
    signal: int | None = None  # 1 honest, 0 suspicious, None not sampled


@dataclass
class Scorer:
    cfg: ScoringConfig
    spec: JobSpec
    theta: State
    shard_bytes: dict[int, bytes]  # shard index -> npz bytes, for the shards needed this round
    random_shard: int
    _tensors: dict[int, tuple[torch.Tensor, torch.Tensor]] = field(default_factory=dict)
    _base_loss: dict[int, float] = field(default_factory=dict)

    def _shard(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        if index not in self._tensors:
            shard = data.Shard.from_bytes(self.shard_bytes[index])
            n = min(len(shard), self.cfg.max_eval_samples)
            self._tensors[index] = data.to_tensors(data.Shard(shard.x[:n], shard.y[:n]))
        return self._tensors[index]

    def _loss(self, state: State, index: int) -> float:
        x, y = self._shard(index)
        loss, _ = diloco.evaluate(self.spec.model.arch, self.spec.model.config, state, x, y, device=torch.device("cpu"))
        return loss

    def base_loss(self, index: int) -> float:
        if index not in self._base_loss:
            self._base_loss[index] = self._loss(self.theta, index)
        return self._base_loss[index]

    def cheap_checks(self, delta: State, median_norm: float | None) -> str:
        """Return a rejection reason, or an empty string."""
        if set(delta) != set(self.theta):
            return "tensor names differ from the model"
        total = 0.0
        for name, tensor in delta.items():
            if tuple(tensor.shape) != tuple(self.theta[name].shape):
                return f"shape mismatch on {name}"
            if not torch.isfinite(tensor).all():
                return "non-finite values"
            total += float(tensor.float().pow(2).sum())
        norm = math.sqrt(total)
        if norm == 0.0:
            return "empty update"
        if median_norm and norm > self.cfg.norm_clip * median_norm:
            return f"update norm {norm:.3g} exceeds {self.cfg.norm_clip}× the round median {median_norm:.3g}"
        return ""

    def loss_delta(self, delta: State, assigned: int) -> tuple[float, float]:
        candidate = {k: self.theta[k] - delta[k] for k in self.theta}
        gain_assigned = self.base_loss(assigned) - self._loss(candidate, assigned)
        probe = self.random_shard if self.random_shard != assigned else next((i for i in self.shard_bytes if i != assigned), assigned)
        gain_random = self.base_loss(probe) - self._loss(candidate, probe)
        return gain_assigned, gain_random

    def judge(self, delta: State, assigned: int, median_norm: float | None, honesty: float, sampled: bool) -> Verdict:
        reason = self.cheap_checks(delta, median_norm)
        if reason:
            return Verdict(False, reason, score=0.0, signal=0)
        if honesty < self.cfg.honesty_floor:
            return Verdict(False, f"honesty {honesty:.2f} below floor {self.cfg.honesty_floor}", score=0.0)
        if not sampled:
            return Verdict(True, "", score=1.0)
        gain_assigned, gain_random = self.loss_delta(delta, assigned)
        signal = 1 if gain_assigned > 0 else 0
        if gain_assigned < self.cfg.min_gain:
            return Verdict(False, f"loss on the assigned shard got worse by {-gain_assigned:.3f}", score=0.0, gain_assigned=gain_assigned, gain_random=gain_random, signal=0)
        return Verdict(True, "", score=max(gain_assigned, 0.0), gain_assigned=gain_assigned, gain_random=gain_random, signal=signal)


def flatten(delta: State) -> torch.Tensor:
    return torch.cat([t.float().reshape(-1) for _, t in sorted(delta.items())])


def duplicates(deltas: list[tuple[int, State]], threshold: float = 0.98) -> dict[int, tuple[int, float]]:
    """Return {later index: (earlier index, cosine)} for pairs of near-identical updates.
    `deltas` is ordered by commit time, earliest first."""
    flats = [(i, flatten(d)) for i, d in deltas]
    out: dict[int, tuple[int, float]] = {}
    for a in range(len(flats)):
        ia, va = flats[a]
        na = float(va.norm())
        if na == 0 or not math.isfinite(na):
            continue
        for b in range(a + 1, len(flats)):
            ib, vb = flats[b]
            if ib in out:
                continue
            nb = float(vb.norm())
            if nb == 0 or not math.isfinite(nb):
                continue
            cos = float(torch.dot(va, vb) / (na * nb))
            if cos > threshold:
                out[ib] = (ia, cos)
    return out


def delta_norm(delta: State) -> float:
    return math.sqrt(sum(float(t.float().pow(2).sum()) for t in delta.values()))


def decode_delta(frame_bytes: bytes) -> tuple[fr.Frame, State]:
    frame = fr.decode(frame_bytes)
    return frame, compression.decompress(frame.tensors)


def update_honesty(current: float, signal: int | None, alpha: float) -> float:
    if signal is None:
        return current
    return (1 - alpha) * current + alpha * signal
