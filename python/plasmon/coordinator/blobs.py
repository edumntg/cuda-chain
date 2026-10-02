"""Content-addressed blob store. `local` keeps files under one directory."""

from __future__ import annotations

import os
from pathlib import Path

from ..core import hashing


class BlobError(ValueError):
    pass


class LocalBlobStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, blob_id: str) -> Path:
        if not hashing.is_digest(blob_id):
            raise BlobError("bad blob id")
        return self.root / blob_id[:2] / blob_id

    def exists(self, blob_id: str) -> bool:
        return self.path(blob_id).exists()

    def size(self, blob_id: str) -> int:
        return self.path(blob_id).stat().st_size

    def put(self, data: bytes, expected_id: str | None = None) -> str:
        blob_id = hashing.digest(data)
        if expected_id is not None and expected_id != blob_id:
            raise BlobError("digest mismatch")
        target = self.path(blob_id)
        if target.exists():
            return blob_id
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, target)
        return blob_id

    def get(self, blob_id: str) -> bytes:
        p = self.path(blob_id)
        if not p.exists():
            raise FileNotFoundError(blob_id)
        return p.read_bytes()

    def total_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())
