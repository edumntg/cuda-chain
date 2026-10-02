"""Measure a trained model on the MNIST or Fashion-MNIST test set.

    python examples/mnist/eval.py model.safetensors [--dataset mnist|fashion-mnist]
"""

import argparse

from plasmon.train import data, diloco, weights


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--dataset", choices=["mnist", "fashion-mnist"], default="mnist")
    parser.add_argument("--arch", default="mnist_cnn")
    args = parser.parse_args()
    with open(args.path, "rb") as f:
        theta = weights.from_bytes(f.read())
    _, test = data.load_mnist() if args.dataset == "mnist" else data.load_fashion_mnist()
    x, y = data.to_tensors(test)
    loss, acc = diloco.evaluate(args.arch, {}, theta, x, y)
    print(f"test loss {loss:.4f}  accuracy {acc:.4f}  ({len(y)} images, {args.dataset})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
