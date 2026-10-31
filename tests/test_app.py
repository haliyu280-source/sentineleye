"""Startup, the original /api/health contract, and service endpoints."""

from conftest import ADMIN

ORIGINAL_FIELDS = {"operating_system", "disk_usage", "cpu_usage", "memory_total_mb", "status"}


def test_app_starts_and_database_answers(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_original_health_endpoint_still_returns_its_contract(client):
    # Runs the real sentinel.sh on this machine
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert ORIGINAL_FIELDS <= body.keys()
    assert body["status"] in ("healthy", "warning")
    assert isinstance(body["disk_usage"], int)


def test_health_endpoint_needs_no_credentials(client):
    assert client.get("/api/health", headers={"Authorization": "Bearer nonsense"}).status_code == 200


def test_openapi_documents_the_platform(client):
    paths = client.get("/openapi.json").json()["paths"]
    for path in (
        "/api/health",
        "/api/servers",
        "/api/servers/{server_id}/metrics",
        "/api/agent/metrics",
        "/api/alerts",
        "/api/overview",
    ):
        assert path in paths
    assert client.get("/docs").status_code == 200


def test_management_api_requires_admin_token(client):
    assert client.get("/api/servers").status_code == 401
    assert client.get("/api/servers", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/servers", headers={"Authorization": "Basic abc"}).status_code == 401
    assert client.get("/api/servers", headers=ADMIN).status_code == 200


def test_management_api_disabled_without_configured_admin_token(client, monkeypatch):
    from sentineleye.config import get_settings

    monkeypatch.setenv("SENTINELEYE_ADMIN_TOKEN", "")
    get_settings.cache_clear()
    try:
        assert client.get("/api/servers", headers=ADMIN).status_code == 503
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_repeated_admin_failures_are_rate_limited(client):
    codes = [client.get("/api/servers", headers={"Authorization": "Bearer wrong"}).status_code for _ in range(12)]
    assert codes[:10] == [401] * 10
    assert codes[-1] == 429
