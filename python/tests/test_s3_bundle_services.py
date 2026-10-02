import platform
from pathlib import Path

import boto3
import pytest
import yaml
from moto import mock_aws
from plasmon.coordinator import bundle
from plasmon.coordinator.blobs import BlobError, S3BlobStore
from plasmon.coordinator.config import ServerConfig
from plasmon.trainer import services


@mock_aws
def test_s3_blob_store_roundtrip():
    boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="plasmon-test")
    store = S3BlobStore("plasmon-test", prefix="blobs/")
    data = b"hello plasmon" * 100
    blob_id = store.put(data)
    assert store.exists(blob_id) and store.size(blob_id) == len(data)
    assert store.get(blob_id) == data
    assert store.put(data) == blob_id  # idempotent
    assert not store.exists("0" * 64)
    with pytest.raises(BlobError):
        store.put(data, expected_id="1" * 64)
    with pytest.raises(FileNotFoundError):
        store.get("0" * 64)
    assert store.total_bytes() == len(data)


def test_compose_bundle(tmp_path):
    cfg = ServerConfig(mode="private")
    files = bundle.write_bundle(tmp_path / "deploy", cfg, "plasmon.acme.test", "minio", None)
    names = {f.name for f in files}
    assert names == {"docker-compose.yml", "Caddyfile", ".env", "plasmon-server.yaml"}
    compose = yaml.safe_load((tmp_path / "deploy" / "docker-compose.yml").read_text())
    assert set(compose["services"]) == {"api", "worker", "caddy", "postgres", "minio", "minio-init"}
    assert compose["services"]["api"]["environment"]["PLASMON_RUN_WORKER"] == "0"
    assert "postgresql+psycopg://plasmon:" in compose["services"]["worker"]["environment"]["PLASMON_DB_URL"]
    server_cfg = yaml.safe_load((tmp_path / "deploy" / "plasmon-server.yaml").read_text())
    assert server_cfg["blobs"] == {"kind": "s3", "bucket": "plasmon", "endpoint_url": "http://minio:9000", "path": None, "region": "us-east-1", "access_key": None, "secret_key": None, "prefix": "blobs/"}
    assert server_cfg["public_url"] == "https://plasmon.acme.test"
    env = (tmp_path / "deploy" / ".env").read_text()
    assert "PLASMON_SESSION_SECRET=" in env and "POSTGRES_PASSWORD=" in env
    assert "plasmon.acme.test {" in (tmp_path / "deploy" / "Caddyfile").read_text()

    files = bundle.write_bundle(tmp_path / "ext", cfg, "p.acme.test", "s3://acme-blobs@https://s3.eu-central-1.amazonaws.com", "postgresql+psycopg://u:p@db/plasmon")
    compose = yaml.safe_load((tmp_path / "ext" / "docker-compose.yml").read_text())
    assert set(compose["services"]) == {"api", "worker", "caddy"}
    with pytest.raises(ValueError):
        bundle.write_bundle(tmp_path / "bad", cfg, "x", "ftp://nope", None)


def test_service_files_dry_run():
    out = services.enable(["--hours", "weekdays 19:00-08:00"], dry_run=True)
    system = platform.system()
    if system == "Linux":
        assert "plasmon-trainer.service" in out and "trainer start --hours" in out
    elif system == "Darwin":
        assert "dev.plasmon.trainer.plist" in out
    elif system == "Windows":
        assert "schtasks" in out
    assert "would" in services.disable(dry_run=True)
    unit = services.systemd_unit([])
    assert "ExecStart=" in unit and "-m plasmon trainer start" in unit
    plist = services.launchd_plist(["--name", "mac"])
    assert "<string>--name</string>" in plist and "KeepAlive" in plist
    assert Path(services.NAME + ".service").suffix == ".service"
