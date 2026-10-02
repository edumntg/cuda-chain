"""Shared fixtures: a live coordinator on a free port, and an MNIST subset on disk."""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from plasmon.coordinator.app import create_app
from plasmon.coordinator.config import AuthConfig, PolicyConfig, ServerConfig
from plasmon.train import data


def _test_db_url() -> str | None:
    """PLASMON_TEST_DB_URL runs the suite against PostgreSQL. The schema is dropped first."""
    import os

    url = os.environ.get("PLASMON_TEST_DB_URL")
    if url:
        from plasmon.coordinator import db
        from sqlalchemy import create_engine

        engine = create_engine(url)
        db.Base.metadata.drop_all(engine)
        engine.dispose()
    return url


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    root = tmp_path_factory.mktemp("server")
    port = free_port()
    cfg = ServerConfig(
        mode="home",
        host="127.0.0.1",
        port=port,
        data_dir=str(root),
        db_url=_test_db_url(),
        public_url=f"http://127.0.0.1:{port}",
        auth=AuthConfig(open_registration=True),
        policy=PolicyConfig(heartbeat_interval_s=2, idle_poll_interval_s=1),
        tick_interval_s=0.3,
    )
    app = create_app(cfg)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            httpx.get(f"{base}/v1/healthz", timeout=1).raise_for_status()
            break
        except Exception:
            time.sleep(0.1)
    else:
        raise RuntimeError("server did not start")
    yield base
    srv.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="session")
def dataset_dir(tmp_path_factory) -> Path:
    train, _ = data.load_mnist()
    d = tmp_path_factory.mktemp("mnist")
    (d / "subset.npz").write_bytes(data.Shard(train.x[:6600], train.y[:6600]).to_bytes())
    return d


