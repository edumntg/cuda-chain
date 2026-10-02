"""Submit a job: validate, prepare blobs, upload what the server lacks, create."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .client import Client
from .core import hashing, jobspec
from .train import data, models, weights


def prepare(spec: jobspec.JobSpec, progress: Callable[[str], None] = lambda s: None) -> dict[str, Any]:
    """Build the initial weights, the shards and the eval split. Returns blobs by id."""
    blobs: dict[str, bytes] = {}
    progress(f"initial weights: {spec.model.arch} seed {spec.recipe.seed}")
    theta = models.init_weights(spec.model.arch, spec.model.config, spec.recipe.seed)
    if spec.model.init:
        path = Path(spec.model.init)
        if path.exists():
            theta = weights.from_bytes(path.read_bytes())
        else:
            raise FileNotFoundError(f"model.init {spec.model.init} not found")
    init_bytes = weights.to_bytes(theta)
    init_id = hashing.digest(init_bytes)
    blobs[init_id] = init_bytes
    if spec.dataset.source == "builtin://mnist":
        progress("dataset: MNIST (downloading on first use)")
        train, test = data.load_mnist()
        eval_n = max(1000, int(len(test) * spec.dataset.eval_fraction * 10))
        eval_shard = data.Shard(test.x[:eval_n], test.y[:eval_n])
    else:
        source = Path(spec.dataset.source)
        if not source.is_dir():
            raise FileNotFoundError(f"dataset.source {spec.dataset.source} is not a directory of .npz files")
        parts = [data.Shard.from_bytes(p.read_bytes()) for p in sorted(source.glob("*.npz"))]
        if not parts:
            raise FileNotFoundError("no .npz files in dataset.source")
        import numpy as np

        all_x = np.concatenate([p.x for p in parts])
        all_y = np.concatenate([p.y for p in parts])
        n_eval = max(1, int(len(all_y) * spec.dataset.eval_fraction))
        eval_shard = data.Shard(all_x[:n_eval], all_y[:n_eval])
        train = data.Shard(all_x[n_eval:], all_y[n_eval:])
    shards = data.split_shards(train, spec.dataset.shard_size, seed=spec.recipe.seed)
    progress(f"shards: {len(shards)} × {spec.dataset.shard_size} samples, eval {len(eval_shard)} samples")
    manifest = []
    for i, shard in enumerate(shards):
        b = shard.to_bytes()
        sid = hashing.digest(b)
        blobs[sid] = b
        manifest.append({"index": i, "blob": sid, "n": len(shard)})
    eval_bytes = eval_shard.to_bytes()
    eval_id = hashing.digest(eval_bytes)
    blobs[eval_id] = eval_bytes
    return {"init_blob": init_id, "eval_blob": eval_id, "shards": manifest, "blobs": blobs, "param_count": models.parameter_count(theta)}


def submit(client: Client, spec: jobspec.JobSpec, progress: Callable[[str], None] = lambda s: print(s, file=sys.stderr)) -> dict[str, Any]:
    prepared = prepare(spec, progress)
    blobs: dict[str, bytes] = prepared["blobs"]
    missing = client.missing_blobs(list(blobs))
    total = sum(len(blobs[m]) for m in missing)
    progress(f"uploading {len(missing)} of {len(blobs)} blobs ({total / 1e6:.1f} MB); the rest is already on the server")
    for i, blob_id in enumerate(missing, 1):
        client.put_blob(blobs[blob_id], kind="shard" if blob_id != prepared["init_blob"] else "theta")
        if i % 10 == 0 or i == len(missing):
            progress(f"  {i}/{len(missing)}")
    job = client.create_job(
        {
            "spec": spec.model_dump(mode="json"),
            "init_blob": prepared["init_blob"],
            "eval_blob": prepared["eval_blob"],
            "shards": prepared["shards"],
            "param_count": prepared["param_count"],
        }
    )
    return job
