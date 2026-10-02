"""Content addressing with BLAKE3. Blob ids are lowercase hex digests."""

from __future__ import annotations

import os
from pathlib import Path

import blake3

CHUNK = 1 << 20


def digest(data: bytes) -> str:
    return blake3.blake3(data).hexdigest()


def digest_file(path: str | os.PathLike[str]) -> str:
    h = blake3.blake3(max_threads=blake3.blake3.AUTO)
    with open(Path(path), "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def is_digest(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)
