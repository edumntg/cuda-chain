"""Content-addressed blob store. `local` keeps files under one directory."""

from __future__ import annotations

import os
from pathlib import Path

from ..core import hashing


class BlobError(ValueError):
    pass


class LocalBlobStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, blob_id: str) -> Path:
        if not hashing.is_digest(blob_id):
            raise BlobError("bad blob id")
        return self.root / blob_id[:2] / blob_id

    def exists(self, blob_id: str) -> bool:
        return self.path(blob_id).exists()

    def size(self, blob_id: str) -> int:
        return self.path(blob_id).stat().st_size

    def put(self, data: bytes, expected_id: str | None = None) -> str:
        blob_id = hashing.digest(data)
        if expected_id is not None and expected_id != blob_id:
            raise BlobError("digest mismatch")
        target = self.path(blob_id)
        if target.exists():
            return blob_id
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, target)
        return blob_id

    def get(self, blob_id: str) -> bytes:
        p = self.path(blob_id)
        if not p.exists():
            raise FileNotFoundError(blob_id)
        return p.read_bytes()

    def total_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())


class S3BlobStore:
    """Blobs in one bucket under a prefix. Works with MinIO through `endpoint_url`."""

    def __init__(self, bucket: str, prefix: str = "blobs/", endpoint_url: str | None = None, region: str = "us-east-1", access_key: str | None = None, secret_key: str | None = None):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.prefix = prefix
        self.root = Path(f"s3://{bucket}/{prefix}")
        kwargs = {"region_name": region, "config": Config(s3={"addressing_style": "path"} if endpoint_url else {})}
        if endpoint_url:
            kwargs["endpoint_url"] = endpoint_url
        if access_key and secret_key:
            kwargs["aws_access_key_id"], kwargs["aws_secret_access_key"] = access_key, secret_key
        self.client = boto3.client("s3", **kwargs)

    def _key(self, blob_id: str) -> str:
        if not hashing.is_digest(blob_id):
            raise BlobError("bad blob id")
        return f"{self.prefix}{blob_id[:2]}/{blob_id}"

    def exists(self, blob_id: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(blob_id))
            return True
        except self.client.exceptions.ClientError:
            return False

    def size(self, blob_id: str) -> int:
        return self.client.head_object(Bucket=self.bucket, Key=self._key(blob_id))["ContentLength"]

    def put(self, data: bytes, expected_id: str | None = None) -> str:
        blob_id = hashing.digest(data)
        if expected_id is not None and expected_id != blob_id:
            raise BlobError("digest mismatch")
        if not self.exists(blob_id):
            self.client.put_object(Bucket=self.bucket, Key=self._key(blob_id), Body=data)
        return blob_id

    def get(self, blob_id: str) -> bytes:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=self._key(blob_id))["Body"].read()
        except self.client.exceptions.NoSuchKey as e:
            raise FileNotFoundError(blob_id) from e

    def total_bytes(self) -> int:
        total = 0
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix):
            total += sum(o["Size"] for o in page.get("Contents", []))
        return total


def make_store(cfg) -> LocalBlobStore | S3BlobStore:
    if cfg.blobs.kind == "s3":
        if not cfg.blobs.bucket:
            raise BlobError("blobs.bucket is required for the s3 store")
        return S3BlobStore(cfg.blobs.bucket, cfg.blobs.prefix, cfg.blobs.endpoint_url, cfg.blobs.region, cfg.blobs.access_key, cfg.blobs.secret_key)
    return LocalBlobStore(cfg.resolved_blob_path())
