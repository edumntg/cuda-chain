"""Single sign-on against a fake OpenID provider started inside the test."""

from __future__ import annotations

import socket
import threading
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Form
from fastapi.responses import RedirectResponse
from joserfc import jwt
from joserfc.jwk import RSAKey
from plasmon.coordinator.app import create_app
from plasmon.coordinator.config import AuthConfig, OidcConfig, ServerConfig

pytestmark = pytest.mark.timeout(120)


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(app, port) -> uvicorn.Server:
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(100):
        try:
            httpx.get(f"http://127.0.0.1:{port}/", timeout=1)
            break
        except Exception:
            time.sleep(0.05)
    return srv


def fake_idp(port: int, users: dict[str, dict]):
    key = RSAKey.generate_key(2048, parameters={"kid": "test-key", "use": "sig"})
    issuer = f"http://127.0.0.1:{port}"
    app = FastAPI()
    codes: dict[str, dict] = {}

    @app.get("/")
    def root():
        return {"ok": True}

    @app.get("/.well-known/openid-configuration")
    def discovery():
        return {"issuer": issuer, "authorization_endpoint": f"{issuer}/authorize", "token_endpoint": f"{issuer}/token", "jwks_uri": f"{issuer}/jwks", "response_types_supported": ["code"]}

    @app.get("/jwks")
    def jwks():
        return {"keys": [key.as_dict(private=False)]}

    @app.get("/authorize")
    def authorize(client_id: str, redirect_uri: str, state: str, nonce: str, scope: str = "", response_type: str = "code", user: str = "alice"):
        code = f"code-{user}-{len(codes)}"
        codes[code] = {"user": user, "nonce": nonce, "client_id": client_id}
        return RedirectResponse(f"{redirect_uri}?code={code}&state={state}", status_code=302)

    @app.post("/token")
    def token(code: str = Form(), client_id: str = Form(), client_secret: str = Form(""), grant_type: str = Form(""), redirect_uri: str = Form("")):
        entry = codes.pop(code)
        now = int(time.time())
        claims = {"iss": issuer, "aud": client_id, "sub": entry["user"], "iat": now, "exp": now + 300, "nonce": entry["nonce"], **users[entry["user"]]}
        id_token = jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, key)
        return {"access_token": "at", "token_type": "Bearer", "id_token": id_token}

    return app, issuer


def test_sso_login_with_group_mapping(tmp_path):
    idp_port = _port()
    users = {
        "alice": {"email": "alice@acme.test", "name": "Alice", "groups": ["staff", "plasmon-admins"]},
        "bob": {"email": "bob@acme.test", "name": "Bob", "groups": ["staff"]},
    }
    idp_app, issuer = fake_idp(idp_port, users)
    idp = _serve(idp_app, idp_port)
    port = _port()
    cfg = ServerConfig(
        mode="private", host="127.0.0.1", port=port, data_dir=str(tmp_path), public_url=f"http://127.0.0.1:{port}",
        auth=AuthConfig(open_registration=False),
        oidc=OidcConfig(issuer=issuer, client_id="plasmon-web", client_secret="s3cret", admin_group="plasmon-admins"),
        run_worker=False,
    )
    srv = _serve(create_app(cfg), port)
    try:
        base = f"http://127.0.0.1:{port}"
        with httpx.Client(follow_redirects=False, timeout=10) as web:
            r = web.get(f"{base}/login")
            assert "single sign-on" in r.text
            r = web.get(f"{base}/auth/oidc/login?next=/jobs")
            assert r.status_code == 303
            auth_url = r.headers["location"]
            assert auth_url.startswith(f"{issuer}/authorize")
            web.cookies.update(r.cookies)
            # the browser visits the identity provider, which redirects back with a code
            r = httpx.get(auth_url, follow_redirects=False)
            callback = r.headers["location"]
            assert callback.startswith(f"{base}/auth/oidc/callback")
            r = web.get(callback)
            assert r.status_code == 303 and r.headers["location"] == "/jobs"
            web.cookies.update(r.cookies)
            me = web.get(f"{base}/v1/auth/me").json()
            assert me["user"]["email"] == "alice@acme.test" and me["user"]["role"] == "owner"  # first account

        with httpx.Client(follow_redirects=False, timeout=10) as web:
            r = web.get(f"{base}/auth/oidc/login")
            web.cookies.update(r.cookies)
            auth_url = r.headers["location"] + "&user=bob"
            callback = httpx.get(auth_url, follow_redirects=False).headers["location"]
            r = web.get(callback)
            web.cookies.update(r.cookies)
            me = web.get(f"{base}/v1/auth/me").json()
            assert me["user"]["email"] == "bob@acme.test" and me["user"]["role"] == "member"

        # a tampered state is rejected
        with httpx.Client(follow_redirects=False, timeout=10) as web:
            r = web.get(f"{base}/auth/oidc/login")
            web.cookies.update(r.cookies)
            query = parse_qs(urlparse(r.headers["location"]).query)
            r = web.get(f"{base}/auth/oidc/callback?code=x&state=wrong")
            assert r.status_code == 401
            assert query["nonce"]
    finally:
        srv.should_exit = True
        idp.should_exit = True
