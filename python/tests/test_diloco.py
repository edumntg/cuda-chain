"""M1 acceptance: two in-process trainers with DiLoCo and top-k compression reach the
accuracy of one worker trained for the same number of steps, on an MNIST subset."""

import pytest
from plasmon.core import jobspec
from plasmon.train import data, simulate

SPEC = jobspec.loads(
    """
name: mnist-m1
model: {arch: mnist_cnn}
dataset: {source: builtin://mnist, shard_size: 1000}
recipe:
  inner_steps: 50
  batch_size: 64
  inner_optimizer: {name: adamw, lr: 2.0e-3}
  outer_optimizer: {name: nesterov, lr: 0.7, momentum: 0.9}
  compression: {name: topk, topk: 0.1, error_feedback: true}
budget: {rounds: 6}
"""
)


@pytest.fixture(scope="module")
def mnist():
    train, test = data.load_mnist()
    return data.Shard(train.x[:12000], train.y[:12000]), data.Shard(test.x[:2000], test.y[:2000])


def test_two_trainers_match_single_worker(mnist):
    train, test = mnist
    shards = data.split_shards(train, SPEC.dataset.shard_size, seed=1)
    assert len(shards) == 12
    rounds, trainers = SPEC.budget.rounds, 2
    sim = simulate.run(SPEC, shards, test, trainers=trainers, rounds=rounds)
    _, base_acc = simulate.baseline(SPEC, train, test, steps=rounds * SPEC.recipe.inner_steps)
    accs = [round(r.eval_acc, 3) for r in sim.rounds]
    print(f"\ndiloco per round: {accs}  baseline({rounds * SPEC.recipe.inner_steps} steps): {base_acc:.3f}")
    print(f"traffic: {sim.total_frame_bytes:,} B compressed vs {sim.total_dense_bytes:,} B dense "
          f"({100 * sim.total_frame_bytes / sim.total_dense_bytes:.1f} %)")
    assert sim.final_acc >= 0.90
    assert sim.final_acc >= base_acc - 0.05
    assert sim.total_frame_bytes < 0.2 * sim.total_dense_bytes


def test_dense_compression_is_exact_to_fp16(mnist):
    import torch
    from plasmon.core import frame as fr
    from plasmon.train import compression

    delta = {"w": torch.randn(37, 11), "b": torch.randn(11)}
    entries = compression.Compressor(topk=1.0, error_feedback=False).compress(delta)
    back = compression.decompress(fr.decode(fr.encode(fr.Frame("j", 0, "n", "t", 1, entries))).tensors)
    for k, value in delta.items():
        assert torch.allclose(back[k], value.half().float())
        assert back[k].shape == value.shape


def test_error_feedback_carries_the_remainder():
    import torch
    from plasmon.train import compression

    c = compression.Compressor(topk=0.5, error_feedback=True)
    delta = {"w": torch.tensor([4.0, -3.0, 2.0, 1.0])}
    first = c.compress(delta)
    assert sorted(first[0].indices.tolist()) == [0, 1]
    assert torch.allclose(c.residual["w"], torch.tensor([0.0, 0.0, 2.0, 1.0]))
    second = c.compress({"w": torch.zeros(4)})
    assert sorted(second[0].indices.tolist()) == [2, 3]
