"""Datasets as content-addressed shards.

A shard is an `.npz` with `x` (uint8, N×28×28 for MNIST) and `y` (uint8, N). Trainers
fetch only the shard assigned to them. The eval split stays with the coordinator.
"""

from __future__ import annotations

import gzip
import io
import struct
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..paths import cache_dir

MNIST_FILES = {
    "train_x": "train-images-idx3-ubyte.gz",
    "train_y": "train-labels-idx1-ubyte.gz",
    "test_x": "t10k-images-idx3-ubyte.gz",
    "test_y": "t10k-labels-idx1-ubyte.gz",
}
MNIST_MIRRORS = (
    "https://ossci-datasets.s3.amazonaws.com/mnist/",
    "https://storage.googleapis.com/cvdf-datasets/mnist/",
)


@dataclass
class Shard:
    x: np.ndarray
    y: np.ndarray

    def __len__(self) -> int:
        return len(self.y)

    def to_bytes(self) -> bytes:
        buf = io.BytesIO()
        np.savez(buf, x=self.x, y=self.y)
        return buf.getvalue()

    @classmethod
    def from_bytes(cls, data: bytes) -> Shard:
        with np.load(io.BytesIO(data)) as z:
            return cls(x=z["x"], y=z["y"])


def _read_idx(data: bytes) -> np.ndarray:
    magic, _count = struct.unpack(">II", data[:8])
    dims = magic & 0xFF
    shape = struct.unpack(">" + "I" * dims, data[4 : 4 + 4 * dims])
    return np.frombuffer(data[4 + 4 * dims :], dtype=np.uint8).reshape(shape)


def _fetch(name: str, directory: Path) -> bytes:
    path = directory / name
    if path.exists():
        return path.read_bytes()
    directory.mkdir(parents=True, exist_ok=True)
    last: Exception | None = None
    for mirror in MNIST_MIRRORS:
        try:
            with urllib.request.urlopen(mirror + name, timeout=60) as r:
                data = r.read()
            path.write_bytes(data)
            return data
        except (OSError, ValueError) as e:  # try the next mirror
            last = e
    raise RuntimeError(f"could not download {name}: {last}")


def load_mnist(directory: Path | None = None) -> tuple[Shard, Shard]:
    """Return (train, test) as uint8 shards. Files are cached under the plasmon cache dir."""
    directory = directory or cache_dir() / "datasets" / "mnist"
    parts = {k: _read_idx(gzip.decompress(_fetch(v, directory))) for k, v in MNIST_FILES.items()}
    return Shard(parts["train_x"], parts["train_y"]), Shard(parts["test_x"], parts["test_y"])


def split_shards(data: Shard, shard_size: int, seed: int) -> list[Shard]:
    """Shuffle once with `seed`, then cut into shards of `shard_size`. The tail is dropped."""
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(data))
    count = len(data) // shard_size
    return [
        Shard(data.x[order[i * shard_size : (i + 1) * shard_size]], data.y[order[i * shard_size : (i + 1) * shard_size]])
        for i in range(count)
    ]


def to_tensors(shard: Shard):
    import torch

    x = torch.from_numpy(np.array(shard.x, dtype=np.uint8)).float().div_(255.0)
    x = (x - 0.1307) / 0.3081
    if x.dim() == 3:
        x = x.unsqueeze(1)
    y = torch.from_numpy(np.array(shard.y, dtype=np.int64))
    return x, y
