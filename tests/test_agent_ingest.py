from datetime import timedelta

from sqlalchemy import func, select

from conftest import ADMIN, agent_headers
from sentineleye.db import SessionLocal
from sentineleye.models import Metric
from sentineleye.timeutil import utcnow


def test_metric_submission_is_stored_and_updates_server(client, register, submit):
    server_id, token = register()
    response = submit(server_id, token, cpu=12.5, memory=33.0, disk=44.0)
    assert response.status_code == 202
    assert response.json() == {"accepted": True, "server_status": "healthy"}

    server = client.get(f"/api/servers/{server_id}", headers=ADMIN).json()
    assert server["status"] == "healthy"
    assert server["hostname"] == "test-host"
    assert server["os_name"] == "Ubuntu" and server["os_version"] == "24.04"
    assert server["last_seen_at"].endswith("Z")
    assert server["latest"]["cpu_percent"] == 12.5
    assert server["latest"]["memory_percent"] == 33.0

    latest = client.get(f"/api/servers/{server_id}/metrics/latest", headers=ADMIN).json()
    assert latest["disk_percent"] == 44.0


def test_agent_cannot_report_for_another_server(client, register, submit):
    first_id, first_token = register("web-01")
    second_id, _ = register("web-02")
    assert submit(second_id, first_token).status_code == 403
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Metric)) == 0
    assert submit(first_id, first_token).status_code == 202


def test_invalid_metrics_are_rejected(client, register, sample):
    server_id, token = register()
    headers = agent_headers(token)
    bad_payloads = [
        sample(server_id, cpu=150),
        sample(server_id, cpu=-1),
        sample(server_id, hostname="bad host!"),
        {**sample(server_id), "extra_field": 1},
        {**sample(server_id), "collected_at": "2026-01-01T00:00:00"},  # no timezone
    ]
    over_used = sample(server_id)
    over_used["memory"]["used_bytes"] = over_used["memory"]["total_bytes"] + 1
    bad_payloads.append(over_used)
    missing = sample(server_id)
    del missing["disk"]
    bad_payloads.append(missing)

    for payload in bad_payloads:
        assert client.post("/api/agent/metrics", json=payload, headers=headers).status_code == 422


def test_stale_future_and_replayed_samples_are_rejected(client, register, sample):
    server_id, token = register()
    headers = agent_headers(token)
    now = utcnow()

    stale = sample(server_id, at=now - timedelta(minutes=10))
    future = sample(server_id, at=now + timedelta(minutes=10))
    assert client.post("/api/agent/metrics", json=stale, headers=headers).status_code == 422
    assert client.post("/api/agent/metrics", json=future, headers=headers).status_code == 422

    fresh = sample(server_id, at=now)
    assert client.post("/api/agent/metrics", json=fresh, headers=headers).status_code == 202
    assert client.post("/api/agent/metrics", json=fresh, headers=headers).status_code == 409  # replay
    older = sample(server_id, at=now - timedelta(seconds=5))
    assert client.post("/api/agent/metrics", json=older, headers=headers).status_code == 409


def test_oversized_requests_are_rejected(client, register, sample):
    server_id, token = register()
    payload = sample(server_id, agent_version="1.0.0")
    padded = {**payload, "os": {**payload["os"], "name": "x" * 70_000}}
    response = client.post("/api/agent/metrics", json=padded, headers=agent_headers(token))
    assert response.status_code == 413


def test_agent_rate_limit(client, register, submit, monkeypatch):
    from sentineleye.config import get_settings

    monkeypatch.setenv("SENTINELEYE_AGENT_RATE_LIMIT_PER_MINUTE", "3")
    get_settings.cache_clear()
    try:
        server_id, token = register()
        codes = [submit(server_id, token).status_code for _ in range(4)]
        assert codes == [202, 202, 202, 429]
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_reported_delivery_failures_are_recorded(client, register, submit):
    server_id, token = register()
    response = submit(server_id, token, delivery={"failed_attempts": 3, "last_error": "Cannot reach backend: timed out"})
    assert response.status_code == 202
    server = client.get(f"/api/servers/{server_id}", headers=ADMIN).json()
    assert server["failed_deliveries"] == 3
    assert server["last_agent_error"] == "Cannot reach backend: timed out"

    submit(server_id, token)
    server = client.get(f"/api/servers/{server_id}", headers=ADMIN).json()
    assert server["failed_deliveries"] == 0
    assert server["last_agent_error"] is None
