"""Application factory. One process serves the API, the dashboard and the scheduler."""

from __future__ import annotations

import datetime as dt
import logging
import socket
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import __version__
from ..core import identity
from . import api_auth, api_fleet, api_jobs, api_machines, api_misc, db, oidc, web
from .blobs import make_store
from .config import ServerConfig
from .engine import Engine, Scheduler
from .events import Bus
from .sessions import CookieSessions

log = logging.getLogger("plasmon.server")
WEB = Path(__file__).parent / "web"


class State:
    def __init__(self, cfg: ServerConfig):
        self.cfg = cfg
        data_dir = cfg.resolved_data_dir()
        data_dir.mkdir(parents=True, exist_ok=True)
        key_path = cfg.server_key_path()
        if key_path.exists():
            self.server = identity.Identity.load(key_path)
        else:
            self.server = identity.Identity.generate()
            self.server.save(key_path)
        self.engine_db = db.make_engine(cfg.resolved_db_url())
        self.session_factory = db.make_session_factory(self.engine_db)
        self.blobs = make_store(cfg)
        self.bus = Bus()
        self.engine = Engine(self.blobs, self.bus, self.server, cfg.policy.heartbeat_interval_s, cfg.retention, cfg.scoring)
        self.oidc = oidc.Provider(cfg.oidc) if cfg.oidc.enabled else None
        self.sessions = CookieSessions(cfg.auth.session_secret)
        self.scheduler: Scheduler | None = None
        self.started_ts = time.time()
        self.started_at = dt.datetime.now(dt.UTC).isoformat()
        self.templates = Jinja2Templates(directory=str(WEB / "templates"))
        web.install_filters(self.templates)

    def public_url(self, request: Request | None = None) -> str:
        if self.cfg.public_url:
            return self.cfg.public_url.rstrip("/")
        if request is not None:
            return str(request.base_url).rstrip("/")
        return f"http://{lan_ip()}:{self.cfg.port}"


def lan_ip() -> str:
    """Best-effort LAN address, used in the device-code prompt and in `server start` output."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def create_app(cfg: ServerConfig) -> FastAPI:
    state = State(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if cfg.run_worker:
            state.scheduler = Scheduler(state.engine, state.session_factory, cfg.tick_interval_s)
            state.scheduler.start()
        log.info("plasmon %s listening on %s:%s (%s mode)", __version__, cfg.host, cfg.port, cfg.mode)
        yield
        if state.scheduler:
            state.scheduler.stop()

    app = FastAPI(title="plasmon coordinator", version=__version__, lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.plasmon = state
    app.include_router(api_auth.router)
    app.include_router(api_machines.router)
    app.include_router(api_jobs.router)
    app.include_router(api_misc.router)
    app.include_router(api_fleet.router)
    app.include_router(oidc.router)
    app.include_router(web.router)
    app.mount("/static", StaticFiles(directory=str(WEB / "static")), name="static")

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "internal error, see server log"}, status_code=500)

    return app
