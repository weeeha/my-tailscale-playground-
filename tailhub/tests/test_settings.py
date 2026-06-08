from tailhub.settings import Settings


def test_defaults():
    s = Settings()
    assert s.probe_port == 9100
    assert s.scrape_interval_s == 30.0
    assert s.retention_days >= 1
    assert "plantdashboard" in s.probe_hosts
    assert s.api_host and isinstance(s.api_port, int)


def test_env_override(monkeypatch):
    monkeypatch.setenv("TAILHUB_SCRAPE_INTERVAL_S", "5")
    monkeypatch.setenv("TAILHUB_DB_PATH", "/tmp/x.db")
    s = Settings()
    assert s.scrape_interval_s == 5.0
    assert s.db_path == "/tmp/x.db"
