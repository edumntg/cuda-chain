"""Credential files shared with the Rust CLI: credentials.toml (user) and machine.toml."""

from __future__ import annotations

import os
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

from .paths import config_dir


@dataclass
class UserCredentials:
    server: str
    user: str
    token: str


@dataclass
class MachineCredentials:
    server: str
    node_id: str
    token: str
    machine_id: str = ""


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'{k} = "{v}"' for k, v in data.items()]
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def user_path() -> Path:
    return config_dir() / "credentials.toml"


def machine_path() -> Path:
    return config_dir() / "machine.toml"


def load_user() -> UserCredentials | None:
    p = user_path()
    if not p.exists():
        return None
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    return UserCredentials(data["server"], data.get("user", ""), data["token"])


def save_user(creds: UserCredentials) -> None:
    _write(user_path(), asdict(creds))


def clear_user() -> None:
    p = user_path()
    if p.exists():
        p.unlink()


def load_machine(path: Path | None = None) -> MachineCredentials | None:
    p = path or machine_path()
    if not p.exists():
        return None
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    return MachineCredentials(data["server"], data["node_id"], data["token"], data.get("machine_id", ""))


def save_machine(creds: MachineCredentials, path: Path | None = None) -> None:
    _write(path or machine_path(), asdict(creds))
