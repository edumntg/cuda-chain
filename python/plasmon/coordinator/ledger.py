"""Hash-chained ledger. Each entry hashes its body and the previous entry's hash and
carries the server's Ed25519 signature. `verify` recomputes the chain."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core import canonical, hashing, identity
from . import db

GENESIS = "0" * 64


def _entry_hash(kind: str, body: dict[str, Any], prev_hash: str, at_iso: str) -> str:
    return hashing.digest(canonical.dumps({"kind": kind, "body": body, "prev": prev_hash, "at": at_iso}))


def append(session: Session, server: identity.Identity, kind: str, body: dict[str, Any]) -> db.LedgerEntry:
    last = session.scalar(select(db.LedgerEntry).order_by(db.LedgerEntry.seq.desc()).limit(1))
    prev = last.hash if last else GENESIS
    at = db.now()
    at_iso = at.isoformat()
    h = _entry_hash(kind, body, prev, at_iso)
    entry = db.LedgerEntry(at=at, kind=kind, body=body, prev_hash=prev, hash=h, signature=server.sign({"hash": h}))
    session.add(entry)
    session.flush()
    return entry


def verify(session: Session, server_node_id: str) -> tuple[bool, int, str]:
    """Return (ok, entries checked, first problem)."""
    prev = GENESIS
    count = 0
    for entry in session.scalars(select(db.LedgerEntry).order_by(db.LedgerEntry.seq)):
        count += 1
        if entry.prev_hash != prev:
            return False, count, f"entry {entry.seq}: prev hash does not match"
        expected = _entry_hash(entry.kind, entry.body, entry.prev_hash, entry.at.isoformat())
        if expected != entry.hash:
            return False, count, f"entry {entry.seq}: hash does not match body"
        if not identity.verify(server_node_id, {"hash": entry.hash}, entry.signature):
            return False, count, f"entry {entry.seq}: bad signature"
        prev = entry.hash
    return True, count, ""
