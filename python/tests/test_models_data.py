"""The two larger architectures and the two new data kinds: colour images and byte-level text."""

from __future__ import annotations

import io
import pickle
import tarfile
from pathlib import Path

import numpy as np
import pytest
import torch
from plasmon.core import jobspec
from plasmon.train import data, diloco, models


def test_architectures_forward_shapes():
    cnn = models.build("cifar_cnn", {"width": 16})
    assert cnn(torch.zeros(2, 3, 32, 32)).shape == (2, 10)
    lm = models.build("char_lm", {"vocab": 128, "block_size": 16, "d_model": 32, "layers": 1, "heads": 2})
    assert lm(torch.zeros(2, 16, dtype=torch.long)).shape == (2, 128, 16)
    a = models.init_weights("char_lm", {"vocab": 128, "block_size": 16, "d_model": 32, "layers": 1, "heads": 2}, 7)
    b = models.init_weights("char_lm", {"vocab": 128, "block_size": 16, "d_model": 32, "layers": 1, "heads": 2}, 7)
    assert all(torch.equal(a[k], b[k]) for k in a), "the same seed must give the same weights on every machine"


def test_to_tensors_handles_grey_colour_and_text():
    rng = np.random.default_rng(0)
    grey = data.Shard((rng.random((4, 28, 28)) * 255).astype(np.uint8), rng.integers(0, 10, 4).astype(np.uint8))
    x, y = data.to_tensors(grey)
    assert x.shape == (4, 1, 28, 28) and y.dtype == torch.int64
    colour = data.Shard((rng.random((4, 32, 32, 3)) * 255).astype(np.uint8), rng.integers(0, 10, 4).astype(np.uint8))
    x, y = data.to_tensors(colour)
    assert x.shape == (4, 3, 32, 32) and abs(float(x.mean())) < 2.0
    text = data.encode_text(b"to be or not to be, that is the question " * 20, block_size=16)
    x, y = data.to_tensors(text)
    assert x.dtype == torch.int64 and x.shape == y.shape and x.shape[1] == 16
    assert torch.equal(x[0, 1:], y[0, :-1]), "y is x shifted by one character"


def test_text_source_file_and_split(tmp_path):
    path = tmp_path / "corpus.txt"
    path.write_bytes(b"abcdefghij" * 200)
    train, test = data.load_source(str(path), eval_fraction=0.1, block_size=16)
    assert train.x.dtype == np.int32 and len(train) > len(test) > 0
    with pytest.raises(ValueError):
        data.encode_text(b"short", 16)


def _fake_cifar_archive(path: Path, per_batch: int = 20) -> None:
    rng = np.random.default_rng(1)
    with tarfile.open(path, "w:gz") as tar:
        for name in [f"data_batch_{i}" for i in range(1, 6)] + ["test_batch"]:
            payload = pickle.dumps({"data": (rng.random((per_batch, 3072)) * 255).astype(np.uint8), "labels": rng.integers(0, 10, per_batch).tolist()})
            info = tarfile.TarInfo(f"cifar-10-batches-py/{name}")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))


def test_cifar_archive_parser(tmp_path):
    _fake_cifar_archive(tmp_path / "cifar-10-python.tar.gz")
    train, test = data.load_cifar10(tmp_path)
    assert train.x.shape == (100, 32, 32, 3) and train.x.dtype == np.uint8 and test.x.shape == (20, 32, 32, 3)
    assert train.y.shape == (100,)


def test_real_cifar_archive_when_cached():
    cached = data.cache_dir() / "datasets" / "cifar10" / "cifar-10-python.tar.gz"
    if not cached.exists():
        pytest.skip("CIFAR-10 archive not in the cache")
    train, test = data.load_cifar10()
    assert train.x.shape == (50000, 32, 32, 3) and test.x.shape == (10000, 32, 32, 3)
    assert set(np.unique(test.y)) == set(range(10))


def test_inner_round_and_evaluate_on_colour_and_text():
    rng = np.random.default_rng(0)
    colour = data.Shard((rng.random((64, 32, 32, 3)) * 255).astype(np.uint8), rng.integers(0, 10, 64).astype(np.uint8))
    x, y = data.to_tensors(colour)
    recipe = jobspec.RecipeSpec(inner_steps=2, batch_size=8)
    theta = models.init_weights("cifar_cnn", {"width": 8}, 0)
    result = diloco.inner_round("cifar_cnn", {"width": 8}, theta, x, y, recipe, seed=1, device=torch.device("cpu"))
    assert set(result.delta) == set(theta) and np.isfinite(result.loss_end)
    loss, acc = diloco.evaluate("cifar_cnn", {"width": 8}, theta, x, y, device=torch.device("cpu"))
    assert np.isfinite(loss) and 0.0 <= acc <= 1.0

    cfg = {"vocab": 128, "block_size": 16, "d_model": 32, "layers": 1, "heads": 2}
    text = data.encode_text(b"the quick brown fox jumps over the lazy dog. " * 40, block_size=16)
    x, y = data.to_tensors(text)
    theta = models.init_weights("char_lm", cfg, 0)
    result = diloco.inner_round("char_lm", cfg, theta, x, y, recipe, seed=1, device=torch.device("cpu"))
    assert np.isfinite(result.loss_end)
    loss, acc = diloco.evaluate("char_lm", cfg, theta, x, y, device=torch.device("cpu"))
    assert 3.0 < loss < 6.0 and 0.0 <= acc <= 1.0, "loss per character, near ln(vocab) at init"


def test_char_lm_spec_checks_block_size():
    good = jobspec.loads("name: lm\nmodel: {arch: char_lm, config: {block_size: 64}}\ndataset: {source: builtin://tinyshakespeare, block_size: 64}\n")
    assert good.dataset.block_size == 64
    with pytest.raises(ValueError):
        jobspec.loads("name: lm\nmodel: {arch: char_lm, config: {block_size: 128}}\ndataset: {source: builtin://tinyshakespeare, block_size: 64}\n")
