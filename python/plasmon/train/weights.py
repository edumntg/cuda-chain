"""Weights and optimizer state as safetensors blobs."""

from __future__ import annotations

import torch
from safetensors.torch import load as st_load
from safetensors.torch import save as st_save

State = dict[str, torch.Tensor]


def to_bytes(state: State) -> bytes:
    return st_save({k: v.detach().contiguous().cpu() for k, v in state.items()})


def from_bytes(data: bytes) -> State:
    return dict(st_load(data))
