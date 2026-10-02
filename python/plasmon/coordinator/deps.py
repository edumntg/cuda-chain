"""FastAPI dependencies: sessions, the current user or machine, role checks."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from . import auth, db


@dataclass
class Principal:
    user: db.User | None = None
    machine: db.Machine | None = None
    scopes: set[str] | None = None
    token: db.Token | None = None

    @property
    def role(self) -> str:
        return self.user.role if self.user else "machine"


def get_state(request: Request):
    return request.app.state.plasmon


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.plasmon.session_factory() as session:
        yield session


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def principal_optional(request: Request, session: Session = Depends(get_session)) -> Principal:
    secret = _bearer(request)
    if secret:
        tok = auth.resolve_token(session, secret)
        if tok is None:
            raise HTTPException(401, "invalid or expired token")
        scopes = set(filter(None, tok.scopes.split(",")))
        if tok.user_id:
            user = session.get(db.User, tok.user_id)
            if user is None or user.disabled:
                raise HTTPException(401, "user disabled")
            return Principal(user=user, scopes=scopes, token=tok)
        machine = session.get(db.Machine, tok.machine_id)
        return Principal(machine=machine, scopes=scopes, token=tok)
    state = request.app.state.plasmon
    user_id = state.sessions.read(request)
    if user_id:
        user = session.get(db.User, user_id)
        if user and not user.disabled:
            return Principal(user=user, scopes=set(auth.ROLE_SCOPES[user.role]))
    return Principal()


def current_user(p: Principal = Depends(principal_optional)) -> db.User:
    if p.user is None:
        raise HTTPException(401, "login required")
    return p.user


def current_machine(p: Principal = Depends(principal_optional)) -> db.Machine:
    if p.machine is None:
        raise HTTPException(401, "machine token required")
    return p.machine


def require_role(minimum: str):
    def dep(user: db.User = Depends(current_user)) -> db.User:
        if not auth.role_at_least(user.role, minimum):
            raise HTTPException(403, f"this needs the {minimum} role or higher; you are {user.role}")
        return user

    return dep


def require_scope(scope: str):
    def dep(p: Principal = Depends(principal_optional)) -> Principal:
        if p.scopes is None or scope not in p.scopes:
            raise HTTPException(403, f"token lacks scope {scope}")
        return p

    return dep
