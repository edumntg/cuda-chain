import json
from pathlib import Path

import numpy as np
import pytest
from plasmon.core import assignment, canonical, frame, hashing, identity, jobspec

VECTORS = Path(__file__).parent / "vectors" / "v1.json"


def test_canonical_sorts_keys_and_strips_whitespace():
    assert canonical.dumps({"b": 1, "a": [True, None, "ñ"]}) == '{"a":[true,null,"ñ"],"b":1}'.encode()


def test_canonical_rejects_floats():
    with pytest.raises(canonical.CanonicalError):
        canonical.dumps({"loss": 0.5})


def test_identity_sign_verify_roundtrip():
    ident = identity.Identity.generate()
    payload = {"job": "j1", "round": 3, "blob": "ab" * 32}
    sig = ident.sign(payload)
    assert identity.verify(ident.node_id, payload, sig)
    assert not identity.verify(ident.node_id, {**payload, "round": 4}, sig)
    assert not identity.verify("00" * 32, payload, sig)


def test_identity_save_load(tmp_path):
    ident = identity.Identity.generate()
    path = tmp_path / "k" / "machine.key"
    ident.save(path)
    assert identity.Identity.load(path).node_id == ident.node_id
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_hashing_matches_known_vector():
    # BLAKE3 of the empty input, from the reference implementation.
    assert hashing.digest(b"") == "af1349b9f5f9a1a6a0404dea36dcc9499bcb25c9adc112b7cc9a93cae41f3262"
    assert hashing.is_digest(hashing.digest(b"x"))


def test_frame_roundtrip_sparse_and_dense():
    sparse = frame.TensorEntry(
        "w", (4, 3), np.array([0, 5, 11], dtype=np.uint32), np.array([1.5, -2, 0.25], np.float16)
    )
    dense = frame.TensorEntry("b", (3,), None, np.array([1, 2, 3], np.float16))
    f = frame.Frame("job", 7, "n" * 64, "t" * 64, 320, [sparse, dense], {"loss_end": 0.5})
    data = frame.encode(f)
    back = frame.decode(data)
    assert back.round == 7 and back.samples == 320 and back.meta == {"loss_end": 0.5}
    dw = frame.to_dense(back.tensors[0])
    assert dw.shape == (4, 3) and dw[0, 0] == 1.5 and dw[1, 2] == -2 and dw[3, 2] == 0.25
    assert np.count_nonzero(dw) == 3
    assert frame.to_dense(back.tensors[1]).tolist() == [1, 2, 3]
    assert back.kind == frame.KIND_SPARSE


def test_frame_rejects_corruption():
    f = frame.Frame("job", 0, "n", "t", 1, [frame.TensorEntry("b", (2,), None, np.zeros(2, np.float16))])
    data = bytearray(frame.encode(f))
    data[0:4] = b"NOPE"
    with pytest.raises(frame.FrameError):
        frame.decode(bytes(data))
    bad_idx = frame.TensorEntry("w", (2,), np.array([5], np.uint32), np.array([1], np.float16))
    with pytest.raises(frame.FrameError):
        frame.decode(frame.encode(frame.Frame("job", 0, "n", "t", 1, [bad_idx])))


def test_assignment_is_deterministic_and_in_range():
    a = assignment.shard_index("seed", 3, "node-a", 60)
    assert a == assignment.shard_index("seed", 3, "node-a", 60)
    assert 0 <= a < 60
    spread = {assignment.shard_index("seed", r, "node-a", 60) for r in range(200)}
    assert len(spread) > 30


def test_jobspec_validates_and_rejects():
    spec = jobspec.loads(
        """
name: mnist-home
model: {arch: mnist_cnn}
dataset: {source: builtin://mnist}
recipe: {inner_steps: 20}
budget: {rounds: 3}
"""
    )
    assert spec.recipe.inner_steps == 20 and spec.recipe.outer_optimizer.lr == 0.7
    with pytest.raises(ValueError):
        jobspec.loads("name: x\nmodel: {arch: resnet999}\ndataset: {source: builtin://mnist}\n")
    with pytest.raises(ValueError):
        jobspec.loads(
            "name: x\nmodel: {arch: mlp}\ndataset: {source: builtin://mnist}\n"
            "requirements: {min_trainers: 4, max_trainers: 2}\n"
        )
    with pytest.raises(ValueError):
        jobspec.loads("name: x\nmodel: {arch: mlp}\ndataset: {source: builtin://mnist}\nextra: 1\n")


def test_vectors_file_is_consistent():
    """The Rust crate checks the same file. Regenerate with scripts/make_vectors.py."""
    vec = json.loads(VECTORS.read_text())
    for case in vec["canonical"]:
        assert canonical.dumps(case["value"]).decode() == case["json"]
    for case in vec["blake3"]:
        assert hashing.digest(case["input"].encode()) == case["digest"]
    for case in vec["sign"]:
        ident = identity.Identity.from_seed(bytes.fromhex(case["seed"]))
        assert ident.node_id == case["node_id"]
        assert ident.sign(case["payload"]) == case["signature"]
        assert identity.verify(case["node_id"], case["payload"], case["signature"])
    for case in vec["assignment"]:
        assert assignment.shard_index(case["seed"], case["round"], case["node"], case["shards"]) == case["index"]
