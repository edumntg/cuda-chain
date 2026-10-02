"""Deterministic shard assignment.

shard(job_seed, round, node_id) = blake3(job_seed || round || node_id) mod num_shards.
Every party can recompute it, and a trainer cannot pick an easy shard.
"""

from __future__ import annotations

import struct

import blake3


def shard_index(job_seed: str, round_index: int, node_id: str, num_shards: int) -> int:
    if num_shards <= 0:
        raise ValueError("num_shards must be positive")
    h = blake3.blake3()
    h.update(job_seed.encode("utf-8"))
    h.update(struct.pack("<Q", round_index))
    h.update(node_id.encode("utf-8"))
    return int.from_bytes(h.digest()[:8], "little") % num_shards
