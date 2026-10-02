"""Environment overrides that hosted platforms need: PORT, registration, database URL scheme."""

from plasmon.coordinator import config


def test_env_overrides_for_hosted_platforms(monkeypatch, tmp_path):
    monkeypatch.delenv("PLASMON_PORT", raising=False)
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("PLASMON_OPEN_REGISTRATION", "0")
    monkeypatch.setenv("PLASMON_DB_URL", "postgres://u:p@host:5432/db")
    cfg = config.load(tmp_path / "missing.yaml")
    assert cfg.port == 8080
    assert cfg.auth.open_registration is False
    assert cfg.resolved_db_url() == "postgresql+psycopg://u:p@host:5432/db"
    monkeypatch.setenv("PLASMON_PORT", "7117")
    monkeypatch.setenv("PLASMON_DB_URL", "postgresql+psycopg://u:p@host:5432/db")
    cfg = config.load(tmp_path / "missing.yaml")
    assert cfg.port == 7117 and cfg.resolved_db_url() == "postgresql+psycopg://u:p@host:5432/db"
