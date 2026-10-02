"""Datasets as content-addressed shards.

A shard is an `.npz` with `x` (uint8, N×28×28 for MNIST) and `y` (uint8, N). Trainers
fetch only the shard assigned to them. The eval split stays with the coordinator.

Sources a job can name in `dataset.source`:

- `builtin://mnist`, `builtin://fashion-mnist`: downloaded from public mirrors on first use.
- an `https://` URL of a `.csv`, `.csv.gz` or `.npz` file: downloaded once and cached.
- a local `.csv`, `.csv.gz` or `.npz` file.
- a local directory with the four IDX `.gz` files of MNIST or Fashion-MNIST, or with
  `.npz` shards.

CSV layout: one row per image, the label in the first column (or the last, with
`label_column: last`), then 784 pixel values from 0 to 255. A header row is skipped.
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
FASHION_MIRRORS = (
    "https://raw.githubusercontent.com/zalandoresearch/fashion-mnist/master/data/fashion/",
    "https://github.com/zalandoresearch/fashion-mnist/raw/master/data/fashion/",
)
IDX_ALIASES = {  # other common file names for the same four files
    "train-images-idx3-ubyte.gz": ("train-images.idx3-ubyte.gz", "train-images-idx3-ubyte"),
    "train-labels-idx1-ubyte.gz": ("train-labels.idx1-ubyte.gz", "train-labels-idx1-ubyte"),
    "t10k-images-idx3-ubyte.gz": ("t10k-images.idx3-ubyte.gz", "t10k-images-idx3-ubyte"),
    "t10k-labels-idx1-ubyte.gz": ("t10k-labels.idx1-ubyte.gz", "t10k-labels-idx1-ubyte"),
}


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


def _download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "plasmon"})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(path)


def _fetch(name: str, directory: Path, mirrors: tuple[str, ...] = MNIST_MIRRORS) -> bytes:
    path = directory / name
    if path.exists():
        return path.read_bytes()
    last: Exception | None = None
    for mirror in mirrors:
        try:
            _download(mirror + name, path)
            return path.read_bytes()
        except (OSError, ValueError) as e:  # try the next mirror
            last = e
    raise RuntimeError(f"could not download {name}: {last}")


def _maybe_gunzip(data: bytes) -> bytes:
    return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data


def load_mnist(directory: Path | None = None) -> tuple[Shard, Shard]:
    """Return (train, test) as uint8 shards. Files are cached under the plasmon cache dir."""
    directory = directory or cache_dir() / "datasets" / "mnist"
    parts = {k: _read_idx(_maybe_gunzip(_fetch(v, directory))) for k, v in MNIST_FILES.items()}
    return Shard(parts["train_x"], parts["train_y"]), Shard(parts["test_x"], parts["test_y"])


def load_fashion_mnist(directory: Path | None = None) -> tuple[Shard, Shard]:
    """Fashion-MNIST from the Zalando Research repository: same files, same layout."""
    directory = directory or cache_dir() / "datasets" / "fashion-mnist"
    parts = {k: _read_idx(_maybe_gunzip(_fetch(v, directory, FASHION_MIRRORS))) for k, v in MNIST_FILES.items()}
    return Shard(parts["train_x"], parts["train_y"]), Shard(parts["test_x"], parts["test_y"])


def load_idx_dir(directory: Path) -> tuple[Shard, Shard]:
    """A directory with the four IDX files, downloaded by hand. Test files are optional."""
    directory = Path(directory)

    def find(name: str) -> Path | None:
        for candidate in (name, *IDX_ALIASES.get(name, ())):
            p = directory / candidate
            if p.exists():
                return p
        return None

    paths = {k: find(v) for k, v in MNIST_FILES.items()}
    if paths["train_x"] is None or paths["train_y"] is None:
        raise FileNotFoundError(f"{directory}: expected train-images-idx3-ubyte.gz and train-labels-idx1-ubyte.gz")
    train = Shard(_read_idx(_maybe_gunzip(paths["train_x"].read_bytes())), _read_idx(_maybe_gunzip(paths["train_y"].read_bytes())))
    if paths["test_x"] is None or paths["test_y"] is None:
        return train, Shard(train.x[:0], train.y[:0])
    test = Shard(_read_idx(_maybe_gunzip(paths["test_x"].read_bytes())), _read_idx(_maybe_gunzip(paths["test_y"].read_bytes())))
    return train, test


def load_csv(path: Path, label_column: str = "first", image_shape: tuple[int, int] = (28, 28)) -> Shard:
    """Label and pixel columns, one image per row. Gzip and a header row are handled."""
    raw = _maybe_gunzip(Path(path).read_bytes())
    text = raw.decode("utf-8", errors="replace")
    first_line, _, rest = text.partition("\n")
    if first_line and not first_line.strip()[0].isdigit():
        text = rest  # header row
    table = np.loadtxt(io.StringIO(text), delimiter=",", dtype=np.int32, ndmin=2)
    if label_column == "last":
        labels, pixels = table[:, -1], table[:, :-1]
    else:
        labels, pixels = table[:, 0], table[:, 1:]
    expected = image_shape[0] * image_shape[1]
    if pixels.shape[1] != expected:
        raise ValueError(f"{path}: {pixels.shape[1]} pixel columns, expected {expected} for shape {image_shape}")
    x = np.clip(pixels, 0, 255).astype(np.uint8).reshape(-1, *image_shape)
    return Shard(x, labels.astype(np.uint8))


def load_npz(path: Path) -> Shard:
    return Shard.from_bytes(Path(path).read_bytes())


def fetch_url(url: str, directory: Path | None = None) -> Path:
    """Download a public file once. The cache key is the URL."""
    import blake3

    directory = directory or cache_dir() / "datasets" / "urls"
    name = url.rstrip("/").rsplit("/", 1)[-1] or "download"
    path = directory / f"{blake3.blake3(url.encode()).hexdigest()[:16]}-{name}"
    if not path.exists():
        _download(url, path)
    return path


def _load_file(path: Path, label_column: str, image_shape: tuple[int, int]) -> Shard:
    name = path.name.lower()
    if name.endswith(".npz"):
        return load_npz(path)
    if name.endswith((".csv", ".csv.gz", ".txt", ".txt.gz")):
        return load_csv(path, label_column, image_shape)
    raise ValueError(f"{path}: unknown file type; use .csv, .csv.gz or .npz")


def load_source(source: str, eval_source: str | None = None, eval_fraction: float = 0.1, label_column: str = "first", image_shape: tuple[int, int] = (28, 28)) -> tuple[Shard, Shard]:
    """Return (train, eval) for any supported `dataset.source`."""
    if source == "builtin://mnist":
        train, test = load_mnist()
    elif source == "builtin://fashion-mnist":
        train, test = load_fashion_mnist()
    elif source.startswith("builtin://"):
        raise ValueError(f"unknown builtin dataset {source}; use builtin://mnist or builtin://fashion-mnist")
    else:
        if source.startswith(("http://", "https://")):
            path = fetch_url(source)
        else:
            path = Path(source).expanduser()
            if not path.exists():
                raise FileNotFoundError(f"dataset.source {source} does not exist")
        if path.is_dir():
            npz = sorted(path.glob("*.npz"))
            if npz:
                parts = [load_npz(p) for p in npz]
                train = Shard(np.concatenate([p.x for p in parts]), np.concatenate([p.y for p in parts]))
                test = Shard(train.x[:0], train.y[:0])
            else:
                train, test = load_idx_dir(path)
        else:
            train = _load_file(path, label_column, image_shape)
            test = Shard(train.x[:0], train.y[:0])
    if eval_source:
        eval_path = fetch_url(eval_source) if eval_source.startswith(("http://", "https://")) else Path(eval_source).expanduser()
        test = _load_file(eval_path, label_column, image_shape)
    if len(test) == 0:  # no test split: hold out a fraction of the training data
        n_eval = max(1, int(len(train) * eval_fraction))
        test = Shard(train.x[:n_eval], train.y[:n_eval])
        train = Shard(train.x[n_eval:], train.y[n_eval:])
    return train, test


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
