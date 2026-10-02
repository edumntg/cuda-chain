"""Signed cookie sessions for the web dashboard."""

from __future__ import annotations

from fastapi import Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer

COOKIE = "plasmon_session"


class CookieSessions:
    def __init__(self, secret: str, max_age_s: int = 14 * 24 * 3600):
        self.serializer = URLSafeTimedSerializer(secret, salt="plasmon-session")
        self.max_age_s = max_age_s

    def read(self, request: Request) -> str | None:
        raw = request.cookies.get(COOKIE)
        if not raw:
            return None
        try:
            return self.serializer.loads(raw, max_age=self.max_age_s)
        except BadSignature:
            return None

    def write(self, response: Response, user_id: str, secure: bool) -> None:
        response.set_cookie(COOKIE, self.serializer.dumps(user_id), max_age=self.max_age_s, httponly=True, samesite="lax", secure=secure)

    def clear(self, response: Response) -> None:
        response.delete_cookie(COOKIE)
