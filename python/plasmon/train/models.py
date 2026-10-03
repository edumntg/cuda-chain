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


class CifarCnn(nn.Module):
    """A small VGG-style network for 32×32 colour images, about 0.8M parameters. GroupNorm
    instead of BatchNorm: averaged updates then carry no running statistics to reconcile."""

    def __init__(self, width: int = 32, classes: int = 10):
        super().__init__()

        def block(cin: int, cout: int) -> nn.Sequential:
            return nn.Sequential(
                nn.Conv2d(cin, cout, 3, padding=1),
                nn.GroupNorm(8, cout),
                nn.ReLU(),
                nn.Conv2d(cout, cout, 3, padding=1),
                nn.GroupNorm(8, cout),
                nn.ReLU(),
                nn.MaxPool2d(2),
            )

        self.features = nn.Sequential(block(3, width), block(width, width * 2), block(width * 2, width * 4), nn.Flatten())
        self.head = nn.Sequential(nn.Linear(width * 4 * 4 * 4, 256), nn.ReLU(), nn.Linear(256, classes))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.head(self.features(x))


class CharLm(nn.Module):
    """A small causal transformer over bytes. Logits come back as (batch, vocab, time), so the
    classification loss and the accuracy apply position by position without special cases."""

    def __init__(self, vocab: int = 256, block_size: int = 128, d_model: int = 128, layers: int = 4, heads: int = 4):
        super().__init__()
        self.block_size = block_size
        self.tok = nn.Embedding(vocab, d_model)
        self.pos = nn.Embedding(block_size, d_model)
        layer = nn.TransformerEncoderLayer(d_model, heads, dim_feedforward=4 * d_model, dropout=0.0, batch_first=True, norm_first=True)
        self.blocks = nn.TransformerEncoder(layer, layers, enable_nested_tensor=False)
        self.norm = nn.LayerNorm(d_model)
        self.head = nn.Linear(d_model, vocab, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        t = x.shape[1]
        h = self.tok(x) + self.pos(torch.arange(t, device=x.device))
        mask = nn.Transformer.generate_square_subsequent_mask(t, device=x.device)
        h = self.blocks(h, mask=mask, is_causal=True)
        return self.head(self.norm(h)).transpose(1, 2)


_BUILDERS = {"mnist_cnn": MnistCnn, "mlp": Mlp, "cifar_cnn": CifarCnn, "char_lm": CharLm}


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
