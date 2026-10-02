"""In-process simulation of a DiLoCo run: N trainers, one aggregator, no network.

Used by the M1 acceptance test and by `python -m plasmon bench-diloco`. The real
trainer and coordinator reuse the same functions over the wire.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch

from ..core import assignment
from ..core import frame as fr
from ..core.jobspec import JobSpec
from . import compression, data, diloco, models


@dataclass
class RoundStats:
    round: int
    eval_loss: float
    eval_acc: float
    mean_loss_end: float
    frame_bytes: int
    dense_bytes: int


@dataclass
class SimResult:
    rounds: list[RoundStats]
    theta: diloco.State

    @property
    def final_acc(self) -> float:
        return self.rounds[-1].eval_acc

    @property
    def total_frame_bytes(self) -> int:
        return sum(r.frame_bytes for r in self.rounds)

    @property
    def total_dense_bytes(self) -> int:
        return sum(r.dense_bytes for r in self.rounds)


def run(
    spec: JobSpec,
    shards: list[data.Shard],
    eval_shard: data.Shard,
    trainers: int,
    rounds: int,
    device: torch.device | None = None,
) -> SimResult:
    device = device or diloco.pick_device(spec.requirements.device)
    arch, config = spec.model.arch, spec.model.config
    theta = models.init_weights(arch, config, spec.recipe.seed)
    outer = diloco.Outer(spec.recipe.outer_optimizer)
    compressors = [compression.Compressor(spec.recipe.compression.topk if spec.recipe.compression.name == "topk" else 1.0,
                                          spec.recipe.compression.error_feedback) for _ in range(trainers)]
    node_ids = [f"sim-node-{i:02d}" for i in range(trainers)]
    tensors = [data.to_tensors(s) for s in shards]
    ex, ey = data.to_tensors(eval_shard)
    stats: list[RoundStats] = []
    for r in range(rounds):
        deltas, losses, frame_bytes, dense_bytes = [], [], 0, 0
        for i, node in enumerate(node_ids):
            shard_idx = assignment.shard_index(spec.name, r, node, len(shards))
            x, y = tensors[shard_idx]
            result = diloco.inner_round(arch, config, theta, x, y, spec.recipe, seed=hash((spec.recipe.seed, r, i)) & 0xFFFF, device=device)
            entries = compressors[i].compress(result.delta)
            frame = fr.Frame(spec.name, r, node, "sim", result.samples, entries, {"loss_end": result.loss_end})
            encoded = fr.encode(frame)
            frame_bytes += len(encoded)
            dense_bytes += compression.dense_bytes(result.delta)
            deltas.append(compression.decompress(fr.decode(encoded).tensors))
            losses.append(result.loss_end)
        theta = outer.step(theta, diloco.average(deltas))
        eval_loss, eval_acc = diloco.evaluate(arch, config, theta, ex, ey, device=device)
        stats.append(RoundStats(r, eval_loss, eval_acc, sum(losses) / len(losses), frame_bytes, dense_bytes))
    return SimResult(stats, theta)


def baseline(spec: JobSpec, train: data.Shard, eval_shard: data.Shard, steps: int, device: torch.device | None = None) -> tuple[float, float]:
    """One worker, same inner optimizer, `steps` steps on the whole training set."""
    device = device or diloco.pick_device(spec.requirements.device)
    arch, config = spec.model.arch, spec.model.config
    theta = models.init_weights(arch, config, spec.recipe.seed)
    recipe = spec.recipe.model_copy(update={"inner_steps": steps})
    x, y = data.to_tensors(train)
    result = diloco.inner_round(arch, config, theta, x, y, recipe, seed=spec.recipe.seed, device=device)
    final = {k: theta[k] - result.delta[k] for k in theta}
    ex, ey = data.to_tensors(eval_shard)
    return diloco.evaluate(arch, config, final, ex, ey, device=device)
