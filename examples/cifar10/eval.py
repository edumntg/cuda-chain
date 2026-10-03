"""Measure a trained CIFAR-10 model on the 10,000 test images.

    python examples/cifar10/eval.py model.safetensors [--width 32]
"""

import argparse

from plasmon.train import data, diloco, weights


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--width", type=int, default=32, help="the model.config.width of the job")
    args = parser.parse_args()
    with open(args.path, "rb") as f:
        theta = weights.from_bytes(f.read())
    _, test = data.load_cifar10()
    x, y = data.to_tensors(test)
    loss, acc = diloco.evaluate("cifar_cnn", {"width": args.width}, theta, x, y)
    print(f"test loss {loss:.4f}  accuracy {acc:.4f}  ({len(y)} images)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
