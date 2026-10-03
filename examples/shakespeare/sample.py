"""Generate text from a downloaded char_lm model.

    python examples/shakespeare/sample.py model.safetensors --prompt "ROMEO:" --length 400

The model config must match the job (the defaults match examples/shakespeare/job.yaml).
"""

import argparse
import json

import torch
from plasmon.train import models, weights


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--prompt", default="ROMEO:")
    parser.add_argument("--length", type=int, default=400)
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--config", default='{"vocab": 128, "block_size": 128, "d_model": 128, "layers": 4, "heads": 4}')
    args = parser.parse_args()
    config = json.loads(args.config)
    with open(args.path, "rb") as f:
        theta = weights.from_bytes(f.read())
    model = models.build("char_lm", config)
    model.load_state_dict(theta)
    model.eval()
    ids = [min(b, config["vocab"] - 1) for b in args.prompt.encode("utf-8")]
    out = list(ids)
    with torch.no_grad():
        for _ in range(args.length):
            window = torch.tensor([out[-config["block_size"] :]], dtype=torch.long)
            logits = model(window)[0, :, -1] / max(args.temperature, 1e-4)
            probs = torch.softmax(logits, dim=0)
            out.append(int(torch.multinomial(probs, 1)))
    print(bytes(out).decode("utf-8", errors="replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
