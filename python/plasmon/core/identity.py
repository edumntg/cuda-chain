"""Ed25519 machine identity.

The node id is the hex public key (64 characters). The private seed is stored as
32 raw bytes in a file with mode 0600. Signatures cover canonical JSON bytes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from . import canonical


@dataclass(frozen=True)
class Identity:
    private: Ed25519PrivateKey

    @classmethod
    def generate(cls) -> Identity:
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_seed(cls, seed: bytes) -> Identity:
        if len(seed) != 32:
            raise ValueError("seed must be 32 bytes")
        return cls(Ed25519PrivateKey.from_private_bytes(seed))

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> Identity:
        return cls.from_seed(Path(path).read_bytes())

    def save(self, path: str | os.PathLike[str]) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        from cryptography.hazmat.primitives import serialization

        seed = self.private.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        tmp = p.with_suffix(p.suffix + ".tmp")
        with open(tmp, "wb") as f:
            f.write(seed)
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)

    @property
    def node_id(self) -> str:
        return public_key_hex(self.private.public_key())

    def sign(self, payload: Any) -> str:
        """Return the hex signature over the canonical JSON of `payload`."""
        return self.private.sign(canonical.dumps(payload)).hex()


def public_key_hex(key: Ed25519PublicKey) -> str:
    from cryptography.hazmat.primitives import serialization

    return key.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ).hex()


def verify(node_id: str, payload: Any, signature_hex: str) -> bool:
    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(node_id))
        key.verify(bytes.fromhex(signature_hex), canonical.dumps(payload))
        return True
    except (InvalidSignature, ValueError):
        return False
