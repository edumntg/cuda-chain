"""Datasets as content-addressed shards.

A shard is an `.npz` with `x` (uint8, N×28×28 for MNIST) and `y` (uint8, N). Trainers
fetch only the shard assigned to them. The eval split stays with the coordinator.

Sources a job can name in `dataset.source`:

- `builtin://mnist`, `builtin://fashion-mnist`: downloaded from public mirrors on first use.
- `builtin://cifar10`: the CIFAR-10 python archive (163 MB), 32×32 colour images.
- `builtin://tinyshakespeare`: 1.1 MB of Shakespeare as bytes, cut into sequences of
  `dataset.block_size` characters for the `char_lm` architecture.
- an `https://` URL of a `.csv`, `.csv.gz`, `.npz` or `.txt` file: downloaded once and cached.
- a local `.csv`, `.csv.gz`, `.npz` or `.txt` file.
- a local directory with the four IDX `.gz` files of MNIST or Fashion-MNIST, or with
  `.npz` shards.

Image shards hold `x` as uint8 (N×28×28 grey or N×32×32×3 colour). Text shards hold `x` and
`y` as int32 token ids of shape N×block_size (`y` is `x` shifted by one character).

CSV layout: one row per image, the label in the first column (or the last, with
`label_column: last`), then 784 pixel values from 0 to 255. A header row is skipped.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import struct
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
# MD5 of the published archives, the same values torchvision checks. A download that does
# not match is deleted, so an insecure TLS connection cannot feed the trainer bad data.
KNOWN_MD5 = {
    "mnist": {
        "train-images-idx3-ubyte.gz": "f68b3c2dcbeaaa9fbdd348bbdeb94873",
        "train-labels-idx1-ubyte.gz": "d53e105ee54ea40749a09fcbcd1e9432",
        "t10k-images-idx3-ubyte.gz": "9fb629c4189551a2d022fa330f9573f3",
        "t10k-labels-idx1-ubyte.gz": "ec29112dd5afa0611ce80d1b7f02629c",
    },
    "fashion-mnist": {
        "train-images-idx3-ubyte.gz": "8d4fb7e6c68d591d4c3dfef9ec88bf0d",
        "train-labels-idx1-ubyte.gz": "25c81989df183df01b3e8a0aad5dffbe",
        "t10k-images-idx3-ubyte.gz": "bef4ecab320f06d8554ea6380940ec79",
        "t10k-labels-idx1-ubyte.gz": "bb300cfdad3c16e7a12a480ee83cd310",
    },
}
CIFAR10_URL = "https://www.cs.toronto.edu/~kriz/cifar-10-python.tar.gz"
CIFAR10_MD5 = "c58f30108f718f92721af3b95e74349a"
TINYSHAKESPEARE_URL = "https://raw.githubusercontent.com/karpathy/char-rnn/master/data/tinyshakespeare/input.txt"
TINYSHAKESPEARE_MD5 = "6fb458f1232090904fb40fe944165e91"
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


class DownloadError(RuntimeError):
    pass


TLS_HELP = """The download failed because Python did not trust the server's certificate.
  - Python from python.org on macOS: run once
      open "/Applications/Python 3.X/Install Certificates.command"   (X = your version)
  - Behind a company proxy that inspects TLS: point Python at the company CA bundle
      export SSL_CERT_FILE=/path/to/company-ca.pem
  - For the built-in datasets only, you can skip TLS verification; the files are checked
    by MD5 after the download:
      export PLASMON_INSECURE_DOWNLOADS=1
  - Or download the files with curl or a browser and use a local path as dataset.source
    (see examples/mnist/README.md)."""


def _tls_verify() -> bool:
    return os.environ.get("PLASMON_INSECURE_DOWNLOADS", "").lower() not in ("1", "true", "yes")


def _download(url: str, path: Path, expected_md5: str | None = None) -> None:
    """Stream `url` to `path`. httpx brings certifi's CA bundle and honours SSL_CERT_FILE."""
    import httpx

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    digest = hashlib.md5()
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=120, verify=_tls_verify(), headers={"User-Agent": "plasmon"}) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
                    digest.update(chunk)
    except httpx.ConnectError as e:
        tmp.unlink(missing_ok=True)
        if "CERTIFICATE_VERIFY_FAILED" in str(e) or "certificate" in str(e).lower():
            raise DownloadError(f"{url}: {e}\n{TLS_HELP}") from e
        raise DownloadError(f"{url}: {e}") from e
    except httpx.HTTPError as e:
        tmp.unlink(missing_ok=True)
        raise DownloadError(f"{url}: {e}") from e
    if expected_md5 and digest.hexdigest() != expected_md5:
        tmp.unlink(missing_ok=True)
        raise DownloadError(f"{url}: the file does not match the published MD5 ({digest.hexdigest()} != {expected_md5})")
    tmp.replace(path)


def _fetch(name: str, directory: Path, mirrors: tuple[str, ...] = MNIST_MIRRORS, dataset: str = "mnist") -> bytes:
    path = directory / name
    expected = KNOWN_MD5.get(dataset, {}).get(name)
    if path.exists():
        data = path.read_bytes()
        if expected and hashlib.md5(data).hexdigest() != expected:
            path.unlink()  # a damaged or truncated earlier download; fetch again
        else:
            return data
    last: Exception | None = None
    for mirror in mirrors:
        try:
            _download(mirror + name, path, expected)
            return path.read_bytes()
        except DownloadError as e:  # try the next mirror
            last = e
    raise DownloadError(f"could not download {name} from any mirror.\n{last}")


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
    parts = {k: _read_idx(_maybe_gunzip(_fetch(v, directory, FASHION_MIRRORS, "fashion-mnist"))) for k, v in MNIST_FILES.items()}
    return Shard(parts["train_x"], parts["train_y"]), Shard(parts["test_x"], parts["test_y"])


def load_cifar10(directory: Path | None = None) -> tuple[Shard, Shard]:
    """CIFAR-10 from the python archive: 50,000 training and 10,000 test images, N×32×32×3."""
    import pickle
    import tarfile

    directory = directory or cache_dir() / "datasets" / "cifar10"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "cifar-10-python.tar.gz"
    if not path.exists():
        _download(CIFAR10_URL, path, CIFAR10_MD5)
    batches: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    with tarfile.open(path, "r:gz") as tar:
        for member in tar.getmembers():
            name = Path(member.name).name
            if not (name.startswith("data_batch_") or name == "test_batch"):
                continue
            f = tar.extractfile(member)
            if f is None:
                continue
            d = pickle.load(f, encoding="latin1")  # the archive is MD5-pinned above
            x = np.asarray(d["data"], dtype=np.uint8).reshape(-1, 3, 32, 32).transpose(0, 2, 3, 1)
            batches[name] = (x, np.asarray(d["labels"], dtype=np.uint8))
    train_names = sorted(n for n in batches if n.startswith("data_batch_"))
    if not train_names or "test_batch" not in batches:
        raise ValueError(f"{path} does not look like the CIFAR-10 python archive")
    train = Shard(np.concatenate([batches[n][0] for n in train_names]), np.concatenate([batches[n][1] for n in train_names]))
    test = Shard(*batches["test_batch"])
    return train, test


def encode_text(text: bytes, block_size: int) -> Shard:
    """Cut bytes into sequences of `block_size`; `y` is the next character at each position."""
    tokens = np.frombuffer(text, dtype=np.uint8).astype(np.int32)
    count = (len(tokens) - 1) // block_size
    if count < 1:
        raise ValueError(f"the text has {len(tokens)} characters, fewer than one sequence of {block_size + 1}")
    x = np.stack([tokens[i * block_size : (i + 1) * block_size] for i in range(count)])
    y = np.stack([tokens[i * block_size + 1 : (i + 1) * block_size + 1] for i in range(count)])
    return Shard(x, y)


def load_text(path: Path, block_size: int, eval_fraction: float) -> tuple[Shard, Shard]:
    """A text file: the first part trains, the last `eval_fraction` of the characters evaluate."""
    text = path.read_bytes()
    cut = len(text) - int(len(text) * eval_fraction)
    return encode_text(text[:cut], block_size), encode_text(text[cut:], block_size)


def load_tinyshakespeare(block_size: int, eval_fraction: float = 0.1, directory: Path | None = None) -> tuple[Shard, Shard]:
    directory = directory or cache_dir() / "datasets" / "tinyshakespeare"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "input.txt"
    if not path.exists():
        _download(TINYSHAKESPEARE_URL, path, TINYSHAKESPEARE_MD5)
    return load_text(path, block_size, eval_fraction)


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


def load_source(source: str, eval_source: str | None = None, eval_fraction: float = 0.1, label_column: str = "first", image_shape: tuple[int, int] = (28, 28), block_size: int = 128) -> tuple[Shard, Shard]:
    """Return (train, eval) for any supported `dataset.source`."""
    if source == "builtin://mnist":
        train, test = load_mnist()
    elif source == "builtin://fashion-mnist":
        train, test = load_fashion_mnist()
    elif source == "builtin://cifar10":
        train, test = load_cifar10()
    elif source == "builtin://tinyshakespeare":
        train, test = load_tinyshakespeare(block_size, eval_fraction)
    elif source.startswith("builtin://"):
        raise ValueError(f"unknown builtin dataset {source}; use builtin://mnist, builtin://fashion-mnist, builtin://cifar10 or builtin://tinyshakespeare")
    elif source.endswith(".txt") or (source.startswith(("http://", "https://")) and source.split("?")[0].endswith(".txt")):
        path = fetch_url(source) if source.startswith(("http://", "https://")) else Path(source).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"dataset.source {source} does not exist")
        train, test = load_text(path, block_size, eval_fraction)
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


CIFAR_MEAN = (0.4914, 0.4822, 0.4465)
CIFAR_STD = (0.2470, 0.2435, 0.2616)


def to_tensors(shard: Shard):
    """Model-ready tensors: grey images N×1×H×W, colour images N×3×H×W, text N×T token ids."""
    import torch

    x_np = np.asarray(shard.x)
    if x_np.dtype != np.uint8:  # token ids
        x = torch.from_numpy(x_np.astype(np.int64))
    else:
        x = torch.from_numpy(np.array(x_np, dtype=np.uint8)).float().div_(255.0)
        if x.dim() == 4:  # N×H×W×C colour
            x = x.permute(0, 3, 1, 2).contiguous()
            x = (x - torch.tensor(CIFAR_MEAN).view(1, 3, 1, 1)) / torch.tensor(CIFAR_STD).view(1, 3, 1, 1)
        else:
            x = (x - 0.1307) / 0.3081
            if x.dim() == 3:
                x = x.unsqueeze(1)
    y = torch.from_numpy(np.array(shard.y, dtype=np.int64))
    return x, y
