"""Top-k sparsification with error feedback, packed into Δ frames."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import torch

from ..core import frame as fr


@dataclass
class Compressor:
    topk: float = 0.1
    error_feedback: bool = True
    residual: dict[str, torch.Tensor] = field(default_factory=dict)

    def compress(self, delta: dict[str, torch.Tensor]) -> list[fr.TensorEntry]:
        entries = []
        for name, tensor in delta.items():
            flat = tensor.detach().float().reshape(-1)
            if self.error_feedback and name in self.residual:
                flat = flat + self.residual[name]
            if self.topk >= 1.0:
                entries.append(fr.TensorEntry(name, tuple(tensor.shape), None, flat.numpy().astype(np.float16)))
                if self.error_feedback:
                    self.residual[name] = torch.zeros_like(flat)
                continue
            k = max(1, round(self.topk * flat.numel()))
            idx = torch.topk(flat.abs(), k, sorted=False).indices
            values = flat[idx].to(torch.float16)
            if self.error_feedback:
                rest = flat.clone()
                rest[idx] -= values.float()  # what the receiver reconstructs
                self.residual[name] = rest
            entries.append(
                fr.TensorEntry(
                    name,
                    tuple(tensor.shape),
                    idx.to(torch.int64).numpy().astype(np.uint32),
                    values.numpy(),
                )
            )
        return entries


def decompress(entries: list[fr.TensorEntry]) -> dict[str, torch.Tensor]:
    return {e.name: torch.from_numpy(fr.to_dense(e)) for e in entries}


def dense_bytes(delta: dict[str, torch.Tensor]) -> int:
    return sum(t.numel() * 4 for t in delta.values())
