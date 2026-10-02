"""Accounts: register, login, device-code flow, tokens."""

from __future__ import annotations

import datetime as dt
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import auth, db
from .deps import Principal, current_user, get_session, get_state, principal_optional

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    name: str = Field(default="", max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str
    label: str = "cli"


def user_out(user: db.User) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name, "role": user.role}


def register_user(session: Session, state, email: str, password: str, name: str) -> db.User:
    email = email.lower().strip()
    count = session.scalar(select(func.count()).select_from(db.User))
    if count and not state.cfg.auth.open_registration:
        raise HTTPException(403, "registration is closed; ask an admin for an invite")
    if session.scalar(select(db.User).where(db.User.email == email)):
        raise HTTPException(409, "an account with that email exists")
    role = "owner" if count == 0 else "member"
    user = db.User(email=email, name=name, password_hash=auth.hash_password(password), role=role)
    session.add(user)
    session.flush()
    session.add(db.AuditEvent(actor_id=user.id, action="user.register", target=user.id, detail={"role": role}))
    session.commit()
    return user


@router.post("/register")
def register(body: RegisterIn, session: Session = Depends(get_session), state=Depends(get_state)):
    user = register_user(session, state, body.email, body.password, body.name)
    return {"user": user_out(user)}


@router.post("/login")
def login(body: LoginIn, session: Session = Depends(get_session), state=Depends(get_state)):
    user = session.scalar(select(db.User).where(db.User.email == body.email.lower().strip()))
    if user is None or user.disabled or not auth.verify_password(user.password_hash, body.password):
        raise HTTPException(401, "wrong email or password")
    secret = auth.issue_user_token(session, user, body.label, state.cfg.auth.token_ttl_days)
    session.commit()
    return {"token": secret, "user": user_out(user)}


@router.post("/logout")
def logout(p: Principal = Depends(principal_optional), session: Session = Depends(get_session)):
    if p.token is not None:
        p.token.revoked = True
        session.commit()
    return {"ok": True}


@router.get("/me")
def me(p: Principal = Depends(principal_optional)):
    if p.user is not None:
        return {"user": user_out(p.user), "scopes": sorted(p.scopes or [])}
    if p.machine is not None:
        return {"machine": {"id": p.machine.id, "node_id": p.machine.node_id, "name": p.machine.name}, "scopes": sorted(p.scopes or [])}
    raise HTTPException(401, "not logged in")


# Device-code flow: the CLI asks for a code, the user confirms it in the browser.

class DeviceStart(BaseModel):
    label: str = "cli"


@router.post("/device")
def device_start(body: DeviceStart, request: Request, session: Session = Depends(get_session), state=Depends(get_state)):
    code = db.DeviceCode(
        device_code=secrets.token_urlsafe(32),
        user_code=auth.user_code(),
        expires_at=db.now() + dt.timedelta(seconds=state.cfg.auth.device_code_ttl_s),
        label=body.label,
    )
    session.add(code)
    session.commit()
    base = state.public_url(request)
    return {
        "device_code": code.device_code,
        "user_code": code.user_code,
        "verification_uri": f"{base}/device",
        "verification_uri_complete": f"{base}/device?code={code.user_code}",
        "interval": 3,
        "expires_in": state.cfg.auth.device_code_ttl_s,
    }


class DevicePoll(BaseModel):
    device_code: str


@router.post("/device/token")
def device_token(body: DevicePoll, response: Response, session: Session = Depends(get_session)):
    code = session.get(db.DeviceCode, body.device_code)
    if code is None or code.expires_at < db.now():
        raise HTTPException(410, "code expired; run login again")
    if code.user_id is None:
        response.status_code = 428
        return {"status": "pending"}
    user = session.get(db.User, code.user_id)
    secret = code.token_secret
    session.delete(code)
    session.commit()
    return {"token": secret, "user": user_out(user)}


class DeviceConfirm(BaseModel):
    user_code: str


@router.post("/device/confirm")
def device_confirm(body: DeviceConfirm, user: db.User = Depends(current_user), session: Session = Depends(get_session), state=Depends(get_state)):
    normalized = body.user_code.strip().upper().replace(" ", "")
    if "-" not in normalized and len(normalized) == 8:
        normalized = f"{normalized[:4]}-{normalized[4:]}"
    code = session.scalar(select(db.DeviceCode).where(db.DeviceCode.user_code == normalized))
    if code is None or code.expires_at < db.now():
        raise HTTPException(404, "unknown or expired code")
    if code.user_id is not None:
        raise HTTPException(409, "code already confirmed")
    code.user_id = user.id
    code.token_secret = auth.issue_user_token(session, user, code.label, state.cfg.auth.token_ttl_days)
    session.add(db.AuditEvent(actor_id=user.id, action="auth.device_confirm", target=code.label))
    session.commit()
    return {"ok": True, "label": code.label}


@router.get("/tokens")
def list_tokens(user: db.User = Depends(current_user), session: Session = Depends(get_session)):
    toks = session.scalars(select(db.Token).where(db.Token.user_id == user.id, db.Token.revoked.is_(False)).order_by(db.Token.created_at.desc()))
    return [{"id": t.id, "label": t.label, "created_at": t.created_at, "expires_at": t.expires_at, "last_used_at": t.last_used_at} for t in toks]


@router.delete("/tokens/{token_id}")
def revoke_token(token_id: str, user: db.User = Depends(current_user), session: Session = Depends(get_session)):
    tok = session.get(db.Token, token_id)
    if tok is None or tok.user_id != user.id:
        raise HTTPException(404, "no such token")
    tok.revoked = True
    session.commit()
    return {"ok": True}
