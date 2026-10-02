"""Allow-listed model architectures. A trainer builds a model from a name and a config;
no user code is executed."""

from __future__ import annotations

from typing import Any

import torch
from torch import nn


class MnistCnn(nn.Module):
    def __init__(self, channels: int = 16, hidden: int = 64, classes: int = 10):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, channels, 3),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(channels, channels * 2, 3),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Flatten(),
        )
        self.head = nn.Sequential(nn.Linear(channels * 2 * 5 * 5, hidden), nn.ReLU(), nn.Linear(hidden, classes))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.features(x))


class Mlp(nn.Module):
    def __init__(self, inputs: int = 784, hidden: int = 128, classes: int = 10):
        super().__init__()
        self.net = nn.Sequential(nn.Flatten(), nn.Linear(inputs, hidden), nn.ReLU(), nn.Linear(hidden, classes))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


_BUILDERS = {"mnist_cnn": MnistCnn, "mlp": Mlp}


def build(arch: str, config: dict[str, Any] | None = None) -> nn.Module:
    try:
        builder = _BUILDERS[arch]
    except KeyError as e:
        raise ValueError(f"unknown architecture {arch!r}") from e
    return builder(**(config or {}))


def init_weights(arch: str, config: dict[str, Any] | None, seed: int) -> dict[str, torch.Tensor]:
    """Deterministic initial weights: the same seed gives the same bytes on every machine."""
    torch.manual_seed(seed)
    return {k: v.detach().clone().float() for k, v in build(arch, config).state_dict().items()}


def parameter_count(state: dict[str, torch.Tensor]) -> int:
    return sum(v.numel() for v in state.values())
