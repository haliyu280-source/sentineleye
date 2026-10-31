"""SENTINELEYE_PUBLIC_DASHBOARD: anyone may read, only the admin may change anything."""

import pytest

from conftest import ADMIN
from sentineleye.config import get_settings


@pytest.fixture
def public(monkeypatch):
    monkeypatch.setenv("SENTINELEYE_PUBLIC_DASHBOARD", "true")
    get_settings.cache_clear()
    yield
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture
def fleet(client, register, submit):
    server_id, token = register()
    submit(server_id, token, cpu=95, delivery={"failed_attempts": 2, "last_error": "Cannot reach backend: 10.0.0.5"})
    submit(server_id, token, cpu=95)  # opens a cpu_high alert
    submit(server_id, token, cpu=95, delivery={"failed_attempts": 1, "last_error": "timeout to 10.0.0.5"})
    alert_id = client.get("/api/alerts", headers=ADMIN).json()[0]["id"]
    return server_id, alert_id


READS = [
    "/api/overview",
    "/api/servers",
    "/api/servers/{sid}",
    "/api/servers/{sid}/status",
    "/api/servers/{sid}/metrics/latest",
    "/api/servers/{sid}/metrics?range=1h",
    "/api/alerts",
    "/api/alerts/{aid}",
    "/api/alert-events",
]

WRITES = [
    ("post", "/api/servers", {"name": "intruder"}),
    ("patch", "/api/servers/{sid}", {"enabled": False}),
    ("delete", "/api/servers/{sid}", None),
    ("get", "/api/servers/{sid}/tokens", None),
    ("post", "/api/servers/{sid}/tokens", None),
    ("post", "/api/servers/{sid}/tokens/reissue", None),
    ("post", "/api/alerts/{aid}/acknowledge", {}),
    ("post", "/api/alerts/{aid}/resolve", {}),
]


def test_meta_reports_the_mode(client, public):
    assert client.get("/api/meta").json() == {"version": "1.0.0", "public_dashboard": True}


def test_private_by_default(client, fleet):
    server_id, alert_id = fleet
    assert client.get("/api/meta").json()["public_dashboard"] is False
    for path in READS:
        assert client.get(path.format(sid=server_id, aid=alert_id)).status_code == 401, path


def test_public_mode_allows_reading_without_a_token(client, fleet, public):
    server_id, alert_id = fleet
    for path in READS:
        response = client.get(path.format(sid=server_id, aid=alert_id))
        assert response.status_code == 200, path


def test_public_mode_never_allows_changes(client, fleet, public):
    server_id, alert_id = fleet
    for method, path, body in WRITES:
        kwargs = {"json": body} if body is not None else {}
        response = getattr(client, method)(path.format(sid=server_id, aid=alert_id), **kwargs)
        assert response.status_code == 401, (method, path)
    # Nothing changed
    assert client.get(f"/api/servers/{server_id}").json()["enabled"] is True
    assert client.get(f"/api/alerts/{alert_id}").json()["status"] == "open"


def test_public_view_hides_agent_error_text(client, fleet, public):
    server_id, _ = fleet
    anonymous = client.get(f"/api/servers/{server_id}").json()
    assert anonymous["last_agent_error"] is None
    assert anonymous["failed_deliveries"] == 1
    assert "10.0.0.5" not in client.get("/api/servers").text

    admin = client.get(f"/api/servers/{server_id}", headers=ADMIN).json()
    assert admin["last_agent_error"] == "timeout to 10.0.0.5"


def test_wrong_token_is_still_rejected_in_public_mode(client, fleet, public):
    assert client.get("/api/servers", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_admin_can_still_manage_in_public_mode(client, fleet, public):
    server_id, alert_id = fleet
    assert client.post(f"/api/alerts/{alert_id}/acknowledge", json={}, headers=ADMIN).status_code == 200
    assert client.patch(f"/api/servers/{server_id}", json={"description": "x"}, headers=ADMIN).status_code == 200
