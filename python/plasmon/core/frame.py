"""Binary frame for compressed pseudo-gradients (Δ).

Layout:
    magic  b"PLSM"
    u8     version (1)
    u8     kind    (1 = sparse top-k, 2 = dense)
    u16    reserved (0)
    u64    header length (little endian)
    bytes  header, JSON, UTF-8
    bytes  payload, tensors back to back

Sparse tensor payload: uint32 indices (little endian) then float16 values.
Dense tensor payload: float16 values in row-major order.
The frame id is the BLAKE3 digest of the whole frame.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from typing import Any

import numpy as np

MAGIC = b"PLSM"
VERSION = 1
KIND_SPARSE = 1
KIND_DENSE = 2
_PREFIX = struct.Struct("<4sBBHQ")


class FrameError(ValueError):
    pass


@dataclass
class TensorEntry:
    name: str
    shape: tuple[int, ...]
    indices: np.ndarray | None  # uint32, None for dense
    values: np.ndarray  # float16

    @property
    def numel(self) -> int:
        return int(np.prod(self.shape)) if self.shape else 1


@dataclass
class Frame:
    job: str
    round: int
    node: str
    theta: str
    samples: int
    tensors: list[TensorEntry]
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> int:
        return KIND_DENSE if all(t.indices is None for t in self.tensors) else KIND_SPARSE


def encode(frame: Frame) -> bytes:
    header_tensors = []
    chunks: list[bytes] = []
    offset = 0
    for t in frame.tensors:
        values = np.ascontiguousarray(t.values, dtype=np.float16)
        entry: dict[str, Any] = {
            "name": t.name,
            "shape": list(t.shape),
            "numel": t.numel,
            "val_offset": None,
            "val_len": values.nbytes,
        }
        if t.indices is not None:
            idx = np.ascontiguousarray(t.indices, dtype="<u4")
            if idx.shape != values.shape:
                raise FrameError(f"{t.name}: indices and values differ in length")
            entry["idx_offset"] = offset
            entry["idx_len"] = idx.nbytes
            chunks.append(idx.tobytes())
            offset += idx.nbytes
        entry["val_offset"] = offset
        chunks.append(values.astype("<f2").tobytes())
        offset += values.nbytes
        header_tensors.append(entry)
    header = {
        "job": frame.job,
        "round": frame.round,
        "node": frame.node,
        "theta": frame.theta,
        "samples": frame.samples,
        "meta": frame.meta,
        "tensors": header_tensors,
    }
    header_bytes = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    prefix = _PREFIX.pack(MAGIC, VERSION, frame.kind, 0, len(header_bytes))
    return prefix + header_bytes + b"".join(chunks)


def decode(data: bytes) -> Frame:
    if len(data) < _PREFIX.size:
        raise FrameError("frame too short")
    magic, version, kind, _, header_len = _PREFIX.unpack_from(data, 0)
    if magic != MAGIC:
        raise FrameError("bad magic")
    if version != VERSION:
        raise FrameError(f"unsupported frame version {version}")
    if kind not in (KIND_SPARSE, KIND_DENSE):
        raise FrameError(f"unknown frame kind {kind}")
    start = _PREFIX.size
    end = start + header_len
    if end > len(data):
        raise FrameError("header length exceeds frame")
    try:
        header = json.loads(data[start:end].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise FrameError(f"bad header: {e}") from e
    payload = memoryview(data)[end:]
    tensors: list[TensorEntry] = []
    for entry in header["tensors"]:
        vo, vl = entry["val_offset"], entry["val_len"]
        if vo + vl > len(payload):
            raise FrameError(f"{entry['name']}: values exceed payload")
        values = np.frombuffer(payload[vo : vo + vl], dtype="<f2").astype(np.float16)
        indices = None
        if "idx_offset" in entry:
            io, il = entry["idx_offset"], entry["idx_len"]
            if io + il > len(payload):
                raise FrameError(f"{entry['name']}: indices exceed payload")
            indices = np.frombuffer(payload[io : io + il], dtype="<u4").astype(np.uint32)
            numel = int(np.prod(entry["shape"])) if entry["shape"] else 1
            if indices.size and int(indices.max()) >= numel:
                raise FrameError(f"{entry['name']}: index out of range")
        tensors.append(TensorEntry(entry["name"], tuple(entry["shape"]), indices, values))
    return Frame(
        job=header["job"],
        round=int(header["round"]),
        node=header["node"],
        theta=header["theta"],
        samples=int(header["samples"]),
        tensors=tensors,
        meta=header.get("meta", {}),
    )


def to_dense(entry: TensorEntry) -> np.ndarray:
    """Expand a sparse or dense entry to a float32 array of the tensor's shape."""
    if entry.indices is None:
        return entry.values.astype(np.float32).reshape(entry.shape)
    out = np.zeros(entry.numel, dtype=np.float32)
    out[entry.indices] = entry.values.astype(np.float32)
    return out.reshape(entry.shape)
