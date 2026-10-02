"""Passwords, tokens, roles and scopes."""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import db

_hasher = PasswordHasher()

SCOPES = (
    "jobs:read", "jobs:write", "trainer:read", "trainer:write",
    "fleet:read", "fleet:write", "server:read", "users:write", "billing:write",
)
ROLE_SCOPES = {
    "owner": set(SCOPES),
    "admin": set(SCOPES) - {"billing:write"},
    "operator": {"jobs:read", "trainer:read", "trainer:write", "fleet:read", "fleet:write", "server:read"},
    "member": {"jobs:read", "jobs:write", "trainer:read", "trainer:write"},
    "viewer": {"jobs:read"},
}
MACHINE_SCOPES = {"trainer:read", "trainer:write"}


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def role_at_least(role: str, minimum: str) -> bool:
    return db.ROLE_RANK[role] >= db.ROLE_RANK[minimum]


def new_secret(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def token_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def issue_user_token(session: Session, user: db.User, label: str, ttl_days: int) -> str:
    secret = new_secret("plu")
    session.add(
        db.Token(
            token_hash=token_hash(secret),
            user_id=user.id,
            scopes=",".join(sorted(ROLE_SCOPES[user.role])),
            label=label,
            expires_at=db.now() + dt.timedelta(days=ttl_days),
        )
    )
    return secret


def issue_machine_token(session: Session, machine: db.Machine) -> str:
    secret = new_secret("plm")
    session.add(
        db.Token(
            token_hash=token_hash(secret),
            machine_id=machine.id,
            scopes=",".join(sorted(MACHINE_SCOPES)),
            label=f"machine {machine.name or machine.node_id[:8]}",
        )
    )
    return secret


def resolve_token(session: Session, secret: str) -> db.Token | None:
    tok = session.scalar(select(db.Token).where(db.Token.token_hash == token_hash(secret)))
    if tok is None or tok.revoked:
        return None
    if tok.expires_at is not None and tok.expires_at < db.now():
        return None
    tok.last_used_at = db.now()
    return tok


def user_code() -> str:
    alphabet = "BCDFGHJKLMNPQRSTVWXZ23456789"  # no vowels, no 0/1/O/I
    code = "".join(secrets.choice(alphabet) for _ in range(8))
    return f"{code[:4]}-{code[4:]}"
