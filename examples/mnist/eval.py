"""Measure a trained MNIST model on the test set.

    python examples/mnist/eval.py model.safetensors
"""

import sys

from plasmon.train import data, diloco, weights


def main(path: str) -> int:
    with open(path, "rb") as f:
        theta = weights.from_bytes(f.read())
    _, test = data.load_mnist()
    x, y = data.to_tensors(test)
    loss, acc = diloco.evaluate("mnist_cnn", {}, theta, x, y)
    print(f"test loss {loss:.4f}  accuracy {acc:.4f}  ({len(y)} images)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
