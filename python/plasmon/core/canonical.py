"""Canonical JSON for signed payloads.

A signed payload must contain only strings, integers, booleans, null, lists and
objects. Floats are rejected because Python and Rust format them differently.
"""

from __future__ import annotations

import json
from typing import Any


class CanonicalError(ValueError):
    pass


def _check(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, (bool, str)):
        return
    if isinstance(value, int):
        if not -(2**63) <= value < 2**63:
            raise CanonicalError(f"{path}: integer out of 64-bit range")
        return
    if isinstance(value, float):
        raise CanonicalError(f"{path}: floats are not allowed in signed payloads")
    if isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            _check(item, f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalError(f"{path}: object keys must be strings")
            _check(item, f"{path}.{key}")
        return
    raise CanonicalError(f"{path}: unsupported type {type(value).__name__}")


def dumps(value: Any) -> bytes:
    """Serialize `value` with sorted keys, no whitespace, UTF-8, no escaping of non-ASCII."""
    _check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
