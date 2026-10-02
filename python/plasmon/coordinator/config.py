"""Server configuration: `plasmon-server.yaml` plus `PLASMON_*` environment overrides."""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from ..paths import data_dir


class BlobStoreConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["local"] = "local"
    path: str | None = None  # default: <data_dir>/blobs


class AuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    open_registration: bool = True
    session_secret: str = Field(default_factory=lambda: secrets.token_hex(32))
    token_ttl_days: int = 90
    device_code_ttl_s: int = 600


class PolicyConfig(BaseModel):
    """Org defaults for trainers. A user can tighten these, not loosen them."""

    model_config = ConfigDict(extra="forbid")
    heartbeat_interval_s: int = 10
    idle_poll_interval_s: int = 3
    pause_on_battery: bool = True


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["home", "private", "public"] = "home"
    host: str = "0.0.0.0"
    port: int = 7117
    public_url: str | None = None  # printed in device-code prompts; default http://<host-ip>:<port>
    org_name: str = "home"
    data_dir: str | None = None
    db_url: str | None = None  # default: sqlite:///<data_dir>/plasmon.sqlite3
    blobs: BlobStoreConfig = BlobStoreConfig()
    auth: AuthConfig = AuthConfig()
    policy: PolicyConfig = PolicyConfig()
    run_worker: bool = True  # the round scheduler runs inside the API process
    tick_interval_s: float = 1.0

    def resolved_data_dir(self) -> Path:
        return Path(self.data_dir or data_dir() / "server")

    def resolved_db_url(self) -> str:
        return self.db_url or f"sqlite:///{self.resolved_data_dir() / 'plasmon.sqlite3'}"

    def resolved_blob_path(self) -> Path:
        return Path(self.blobs.path or self.resolved_data_dir() / "blobs")

    def server_key_path(self) -> Path:
        return self.resolved_data_dir() / "server.key"


def default_config_path() -> Path:
    return Path(os.environ.get("PLASMON_SERVER_CONFIG") or data_dir() / "server" / "plasmon-server.yaml")


def load(path: Path | None = None) -> ServerConfig:
    path = path or default_config_path()
    data = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    cfg = ServerConfig.model_validate(data)
    if url := os.environ.get("PLASMON_DB_URL"):
        cfg.db_url = url
    if port := os.environ.get("PLASMON_PORT"):
        cfg.port = int(port)
    if host := os.environ.get("PLASMON_HOST"):
        cfg.host = host
    return cfg


def write(cfg: ServerConfig, path: Path | None = None) -> Path:
    path = path or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg.model_dump(mode="json"), f, sort_keys=False)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path
