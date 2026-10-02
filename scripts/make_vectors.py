"""Write python/tests/vectors/v1.json. Python is the reference; Rust tests read the file."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from plasmon.core import assignment, canonical, hashing, identity

out = {"canonical": [], "blake3": [], "sign": [], "assignment": []}
for value in [{"b": 1, "a": [True, None, "ñ", "日本"]}, [], {}, {"n": -5, "s": "quote\"slash\\"}]:
    out["canonical"].append({"value": value, "json": canonical.dumps(value).decode()})
for text in ["", "plasmon", "thousands of GPUs, one wave"]:
    out["blake3"].append({"input": text, "digest": hashing.digest(text.encode())})
for seed_byte in (0x01, 0x42):
    seed = bytes([seed_byte]) * 32
    ident = identity.Identity.from_seed(seed)
    payload = {"job": "job-1", "round": 12, "node": ident.node_id, "blob": "ab" * 32}
    out["sign"].append(
        {"seed": seed.hex(), "node_id": ident.node_id, "payload": payload, "signature": ident.sign(payload)}
    )
for r in (0, 1, 999):
    out["assignment"].append(
        {"seed": "job-seed", "round": r, "node": "node-a", "shards": 60,
         "index": assignment.shard_index("job-seed", r, "node-a", 60)}
    )
path = Path(__file__).resolve().parents[1] / "python" / "tests" / "vectors" / "v1.json"
path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {path}")
