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
    kind: Literal["local", "s3"] = "local"
    path: str | None = None  # local: default <data_dir>/blobs
    bucket: str | None = None  # s3
    endpoint_url: str | None = None  # s3: MinIO or another S3-compatible service
    region: str = "us-east-1"
    access_key: str | None = None  # default: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
    secret_key: str | None = None
    prefix: str = "blobs/"


class OidcConfig(BaseModel):
    """Single sign-on through OpenID Connect. Groups map to roles."""

    model_config = ConfigDict(extra="forbid")
    issuer: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    scopes: str = "openid email profile"
    groups_claim: str = "groups"
    admin_group: str | None = None
    operator_group: str | None = None
    auto_create_users: bool = True

    @property
    def enabled(self) -> bool:
        return bool(self.issuer and self.client_id)


class ScoringConfig(BaseModel):
    """Verification of updates at round close. See plasmon.validator.scoring."""

    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    sample: float = Field(default=1.0, gt=0, le=1)
    norm_clip: float = 8.0
    min_gain: float = -0.02
    honesty_alpha: float = 0.25
    honesty_floor: float = 0.4
    max_eval_samples: int = 2000


class WebhookConfig(BaseModel):
    """A URL that receives job and fleet events. `format: slack` sends {"text": ...}."""

    model_config = ConfigDict(extra="forbid")
    url: str
    events: list[str] = Field(default_factory=list, description="empty means all: job.completed, job.failed, job.cancelled, machine.offline, machine.error")
    format: Literal["json", "slack"] = "json"


class RetentionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    heartbeats_hours: int = 24
    logs_days: int = 7
    cleanup_interval_s: int = 300


class AuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    open_registration: bool = True
    session_secret: str = Field(default_factory=lambda: secrets.token_hex(32))
    token_ttl_days: int = 90
    device_code_ttl_s: int = 600


class Window(BaseModel):
    """A weekly availability window. `days` uses mon..sun; `end` before `start` crosses midnight."""

    model_config = ConfigDict(extra="forbid")
    days: list[Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]]
    start: str = Field(pattern=r"^\d{2}:\d{2}$")
    end: str = Field(pattern=r"^\d{2}:\d{2}$")


class OrgPolicy(BaseModel):
    """Org defaults for trainers. A user can tighten these, not loosen them.
    Stored in the settings table so an Admin can change them from the dashboard."""

    model_config = ConfigDict(extra="forbid")
    windows: list[Window] = Field(default_factory=list, description="empty means always available")
    pause_on_battery: bool = True
    drain_at_window_end: bool = True
    cpu_threads_cap: int | None = None


class PolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    heartbeat_interval_s: int = 10
    idle_poll_interval_s: int = 3
    defaults: OrgPolicy = OrgPolicy()


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
    oidc: OidcConfig = OidcConfig()
    policy: PolicyConfig = PolicyConfig()
    retention: RetentionConfig = RetentionConfig()
    scoring: ScoringConfig = ScoringConfig()
    webhooks: list[WebhookConfig] = Field(default_factory=list)
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
    if worker := os.environ.get("PLASMON_RUN_WORKER"):
        cfg.run_worker = worker.lower() not in ("0", "false", "no")
    if url := os.environ.get("PLASMON_PUBLIC_URL"):
        cfg.public_url = url
    if secret := os.environ.get("PLASMON_SESSION_SECRET"):
        cfg.auth.session_secret = secret
    if (key := os.environ.get("PLASMON_S3_ACCESS_KEY")) and (sec := os.environ.get("PLASMON_S3_SECRET_KEY")):
        cfg.blobs.access_key, cfg.blobs.secret_key = key, sec
    if secret := os.environ.get("PLASMON_OIDC_CLIENT_SECRET"):
        cfg.oidc.client_secret = secret
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
