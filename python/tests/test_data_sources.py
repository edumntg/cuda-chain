"""Dataset sources: CSV, NPZ, URL download, IDX folder, builtin dispatch, eval split."""

from __future__ import annotations

import gzip
import shutil
import socket
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest
from plasmon.core import jobspec
from plasmon.paths import cache_dir
from plasmon.train import data


def _csv(path: Path, n: int, header: bool, label_last: bool = False, gz: bool = False) -> np.ndarray:
    rng = np.random.default_rng(0)
    pixels = rng.integers(0, 256, (n, 784))
    labels = rng.integers(0, 10, n)
    rows = []
    if header:
        rows.append(",".join(["label", *[f"pixel{i}" for i in range(784)]]))
    for p, lab in zip(pixels, labels):
        cells = [*map(str, p), str(lab)] if label_last else [str(lab), *map(str, p)]
        rows.append(",".join(cells))
    text = "\n".join(rows) + "\n"
    if gz:
        path.write_bytes(gzip.compress(text.encode()))
    else:
        path.write_text(text)
    return labels


def test_csv_header_and_label_position(tmp_path):
    labels = _csv(tmp_path / "a.csv", 20, header=True)
    shard = data.load_csv(tmp_path / "a.csv")
    assert shard.x.shape == (20, 28, 28) and shard.x.dtype == np.uint8
    assert shard.y.tolist() == labels.tolist()
    labels = _csv(tmp_path / "b.csv.gz", 7, header=False, label_last=True, gz=True)
    shard = data.load_csv(tmp_path / "b.csv.gz", label_column="last")
    assert shard.y.tolist() == labels.tolist()
    with pytest.raises(ValueError):
        data.load_csv(tmp_path / "b.csv.gz", label_column="last", image_shape=(16, 16))


def test_npz_and_folder_of_npz(tmp_path):
    shard = data.Shard(np.zeros((5, 28, 28), np.uint8), np.arange(5, dtype=np.uint8))
    (tmp_path / "s0.npz").write_bytes(shard.to_bytes())
    (tmp_path / "s1.npz").write_bytes(shard.to_bytes())
    assert data.load_npz(tmp_path / "s0.npz").y.tolist() == [0, 1, 2, 3, 4]
    train, test = data.load_source(str(tmp_path), eval_fraction=0.2)
    assert len(train) + len(test) == 10 and len(test) == 2


def test_url_download_is_cached(tmp_path, monkeypatch):
    monkeypatch.setenv("PLASMON_CACHE_DIR", str(tmp_path / "cache"))
    site = tmp_path / "site"
    site.mkdir()
    _csv(site / "digits.csv", 30, header=True)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(SimpleHTTPRequestHandler, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{port}/digits.csv"
        path = data.fetch_url(url)
        assert path.exists() and path.name.endswith("-digits.csv")
        (site / "digits.csv").unlink()  # the second call must not hit the network
        assert data.fetch_url(url) == path
        train, test = data.load_source(url, eval_fraction=0.1)
        assert len(train) == 27 and len(test) == 3
        train, test = data.load_source(url, eval_source=url)
        assert len(train) == 30 and len(test) == 30
    finally:
        server.shutdown()


def test_idx_folder_with_hand_downloaded_files(tmp_path):
    src = cache_dir() / "datasets" / "mnist"
    files = list(src.glob("*.gz"))
    if len(files) < 4:
        pytest.skip("MNIST files not in the cache")
    for f in files:
        shutil.copy(f, tmp_path / f.name)
    train, test = data.load_idx_dir(tmp_path)
    assert train.x.shape == (60000, 28, 28) and test.x.shape == (10000, 28, 28)
    (tmp_path / "t10k-images-idx3-ubyte.gz").unlink()
    train, test = data.load_source(str(tmp_path), eval_fraction=0.05)  # no test split: held out
    assert len(test) == 3000 and len(train) == 57000


def test_jobspec_dataset_fields_and_unknown_builtin():
    spec = jobspec.loads(
        "name: x\nmodel: {arch: mlp}\ndataset: {source: 'https://example.com/a.csv', eval_source: 'https://example.com/b.csv', label_column: last}\n"
    )
    assert spec.dataset.label_column == "last" and spec.dataset.image_shape == (28, 28)
    with pytest.raises(ValueError):
        data.load_source("builtin://cifar")
    with pytest.raises(FileNotFoundError):
        data.load_source("/nonexistent/path.csv")
