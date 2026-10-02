"""Where plasmon keeps its files on a machine."""

from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_cache_dir, user_config_dir, user_data_dir

APP = "plasmon"


def config_dir() -> Path:
    return Path(os.environ.get("PLASMON_CONFIG_DIR") or user_config_dir(APP, appauthor=False))


def data_dir() -> Path:
    return Path(os.environ.get("PLASMON_DATA_DIR") or user_data_dir(APP, appauthor=False))


def cache_dir() -> Path:
    return Path(os.environ.get("PLASMON_CACHE_DIR") or user_cache_dir(APP, appauthor=False))


def machine_key_path() -> Path:
    return config_dir() / "machine.key"


def credentials_path() -> Path:
    return config_dir() / "credentials.toml"
