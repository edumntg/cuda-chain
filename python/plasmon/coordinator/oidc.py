"""OpenID Connect login (authorization code flow) with group-to-role mapping.

State and nonce travel in a signed cookie; the ID token is verified against the
provider's JWKS. No session middleware is needed.
"""

from __future__ import annotations

import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from joserfc import jwt
from joserfc.jwk import KeySet
from sqlalchemy import select

from . import auth, db
from .config import OidcConfig

router = APIRouter(include_in_schema=False)
COOKIE = "plasmon_oidc"


class Provider:
    def __init__(self, cfg: OidcConfig):
        self.cfg = cfg
        self._meta: dict | None = None
        self._jwks: KeySet | None = None
        self._jwks_at = 0.0

    def metadata(self) -> dict:
        if self._meta is None:
            url = self.cfg.issuer.rstrip("/") + "/.well-known/openid-configuration"
            self._meta = httpx.get(url, timeout=10).raise_for_status().json()
        return self._meta

    def jwks(self):
        if self._jwks is None or time.time() - self._jwks_at > 3600:
            data = httpx.get(self.metadata()["jwks_uri"], timeout=10).raise_for_status().json()
            self._jwks = KeySet.import_key_set(data)
            self._jwks_at = time.time()
        return self._jwks

    def authorize_url(self, redirect_uri: str, state: str, nonce: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self.cfg.client_id,
            "redirect_uri": redirect_uri,
            "scope": self.cfg.scopes,
            "state": state,
            "nonce": nonce,
        }
        return self.metadata()["authorization_endpoint"] + "?" + urlencode(params)

    def exchange(self, code: str, redirect_uri: str) -> dict:
        r = httpx.post(
            self.metadata()["token_endpoint"],
            data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "client_id": self.cfg.client_id, "client_secret": self.cfg.client_secret or ""},
            timeout=10,
        )
        if r.status_code >= 400:
            raise HTTPException(502, f"token exchange failed: {r.text[:200]}")
        return r.json()

    def claims(self, id_token: str, nonce: str) -> dict:
        try:
            token = jwt.decode(id_token, self.jwks())
            registry = jwt.JWTClaimsRegistry(
                iss={"essential": True, "value": self.cfg.issuer},
                aud={"essential": True, "value": self.cfg.client_id},
                exp={"essential": True},
            )
            registry.validate(token.claims)
        except Exception as e:  # bad signature, wrong issuer or audience, expired
            raise HTTPException(401, f"invalid id token: {e}") from e
        if token.claims.get("nonce") != nonce:
            raise HTTPException(401, "nonce mismatch")
        return dict(token.claims)

    def role_for(self, claims: dict) -> str | None:
        groups = claims.get(self.cfg.groups_claim) or []
        if isinstance(groups, str):
            groups = [groups]
        if self.cfg.admin_group and self.cfg.admin_group in groups:
            return "admin"
        if self.cfg.operator_group and self.cfg.operator_group in groups:
            return "operator"
        return None


def _serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt="plasmon-oidc")


@router.get("/auth/oidc/login")
def oidc_login(request: Request, next: str = "/"):
    state_obj = request.app.state.plasmon
    if not state_obj.cfg.oidc.enabled:
        raise HTTPException(404, "single sign-on is not configured")
    state = secrets.token_urlsafe(16)
    nonce = secrets.token_urlsafe(16)
    redirect_uri = state_obj.public_url(request) + "/auth/oidc/callback"
    url = state_obj.oidc.authorize_url(redirect_uri, state, nonce)
    resp = RedirectResponse(url, status_code=303)
    resp.set_cookie(COOKIE, _serializer(state_obj.cfg.auth.session_secret).dumps({"state": state, "nonce": nonce, "next": next}), max_age=600, httponly=True, samesite="lax")
    return resp


@router.get("/auth/oidc/callback")
def oidc_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    state_obj = request.app.state.plasmon
    if error:
        raise HTTPException(401, f"identity provider error: {error}")
    try:
        saved = _serializer(state_obj.cfg.auth.session_secret).loads(request.cookies.get(COOKIE, ""), max_age=600)
    except BadSignature as e:
        raise HTTPException(401, "login session expired, try again") from e
    if saved["state"] != state:
        raise HTTPException(401, "state mismatch")
    redirect_uri = state_obj.public_url(request) + "/auth/oidc/callback"
    tokens = state_obj.oidc.exchange(code, redirect_uri)
    claims = state_obj.oidc.claims(tokens["id_token"], saved["nonce"])
    email = (claims.get("email") or "").lower()
    if not email:
        raise HTTPException(401, "the identity provider returned no email")
    with state_obj.session_factory() as session:
        user = session.scalar(select(db.User).where(db.User.email == email))
        mapped = state_obj.oidc.role_for(claims)
        if user is None:
            if not state_obj.cfg.oidc.auto_create_users:
                raise HTTPException(403, "no account for this email; ask an admin")
            first = session.scalar(select(db.User)) is None
            user = db.User(email=email, name=claims.get("name", ""), role="owner" if first else (mapped or "member"))
            session.add(user)
            session.flush()
            session.add(db.AuditEvent(actor_id=user.id, action="user.sso_create", target=user.id, detail={"role": user.role}))
        elif mapped and user.role not in ("owner",) and user.role != mapped:
            session.add(db.AuditEvent(actor_id=user.id, action="user.sso_role", target=user.id, detail={"from": user.role, "to": mapped}))
            user.role = mapped
        if user.disabled:
            raise HTTPException(403, "account disabled")
        session.commit()
        user_id = user.id
    next_url = saved.get("next") or "/"
    resp = RedirectResponse(next_url if next_url.startswith("/") else "/", status_code=303)
    state_obj.sessions.write(resp, user_id, secure=request.url.scheme == "https")
    resp.delete_cookie(COOKIE)
    return resp


__all__ = ["Provider", "router", "auth"]
