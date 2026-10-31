from datetime import timedelta

from conftest import ADMIN
from sentineleye.config import get_settings
from sentineleye.db import SessionLocal
from sentineleye.models import Server
from sentineleye.services.alerts import evaluate_heartbeats
from sentineleye.timeutil import utcnow


def alerts(client, **params):
    return client.get("/api/alerts", params=params, headers=ADMIN).json()


def test_single_breach_is_a_warning_but_not_yet_an_alert(client, register, submit):
    server_id, token = register()
    assert submit(server_id, token, cpu=95).json()["server_status"] == "warning"
    assert alerts(client) == []


def test_consecutive_breaches_open_exactly_one_alert(client, register, submit):
    server_id, token = register()
    submit(server_id, token, cpu=91)
    submit(server_id, token, cpu=93)
    opened = alerts(client)
    assert len(opened) == 1
    alert = opened[0]
    assert alert["kind"] == "cpu_high"
    assert alert["status"] == "open"
    assert alert["threshold"] == 80.0
    assert alert["trigger_value"] == 93.0

    # The condition persists: same incident, updated observations
    submit(server_id, token, cpu=97)
    submit(server_id, token, cpu=88)
    still = alerts(client)
    assert len(still) == 1
    assert still[0]["id"] == alert["id"]
    assert still[0]["peak_value"] == 97.0
    assert still[0]["last_value"] == 88.0
    assert still[0]["last_observed_at"] > alert["last_observed_at"]


def test_recovery_resolves_the_alert_and_records_it(client, register, submit):
    server_id, token = register()
    submit(server_id, token, cpu=90)
    submit(server_id, token, cpu=90)
    alert_id = alerts(client)[0]["id"]

    submit(server_id, token, cpu=30)
    detail = client.get(f"/api/alerts/{alert_id}", headers=ADMIN).json()
    assert detail["status"] == "resolved"
    assert detail["resolution"] == "recovered"
    assert [e["event"] for e in detail["events"]] == ["opened", "recovered"]
    assert "back to 30.0%" in detail["events"][-1]["detail"]
    assert client.get(f"/api/servers/{server_id}", headers=ADMIN).json()["status"] == "healthy"

    # A new breach after recovery is a new incident
    submit(server_id, token, cpu=90)
    submit(server_id, token, cpu=90)
    assert len(alerts(client, status="active")) == 1
    assert len(alerts(client)) == 2


def test_memory_and_disk_alerts(client, register, submit):
    server_id, token = register()
    for _ in range(2):
        submit(server_id, token, memory=90, disk=85)
    kinds = sorted(a["kind"] for a in alerts(client))
    assert kinds == ["disk_high", "memory_high"]
    assert client.get(f"/api/servers/{server_id}", headers=ADMIN).json()["status"] == "warning"


def test_per_server_thresholds(client, register, submit):
    strict_id, strict_token = register("strict", thresholds={"cpu": 50})
    relaxed_id, relaxed_token = register("relaxed")
    for _ in range(2):
        submit(strict_id, strict_token, cpu=60)
        submit(relaxed_id, relaxed_token, cpu=60)
    opened = alerts(client)
    assert [(a["server_name"], a["threshold"]) for a in opened] == [("strict", 50.0)]


def test_acknowledge_then_resolve(client, register, submit):
    server_id, token = register()
    submit(server_id, token, disk=95)
    submit(server_id, token, disk=95)
    alert_id = alerts(client)[0]["id"]

    ack = client.post(f"/api/alerts/{alert_id}/acknowledge", json={"note": "Cleaning logs"}, headers=ADMIN)
    assert ack.status_code == 200 and ack.json()["status"] == "acknowledged"
    assert client.post(f"/api/alerts/{alert_id}/acknowledge", headers=ADMIN).status_code == 409

    # Acknowledged alerts are still active, so a continuing breach does not open a duplicate
    submit(server_id, token, disk=96)
    assert len(alerts(client, status="active")) == 1

    resolved = client.post(f"/api/alerts/{alert_id}/resolve", json={"note": "Disk extended"}, headers=ADMIN).json()
    assert resolved["status"] == "resolved" and resolved["resolution"] == "manual"
    assert [e["event"] for e in resolved["events"]] == ["opened", "acknowledged", "resolved"]
    assert resolved["events"][1]["detail"] == "Cleaning logs"
    assert client.post(f"/api/alerts/{alert_id}/resolve", headers=ADMIN).status_code == 409
    assert client.post("/api/alerts/999/resolve", headers=ADMIN).status_code == 404


def test_alert_filters(client, register, submit):
    first_id, first_token = register("a")
    second_id, second_token = register("b")
    for _ in range(2):
        submit(first_id, first_token, cpu=99)
        submit(second_id, second_token, memory=99)
    assert len(alerts(client, server_id=first_id)) == 1
    assert alerts(client, kind="memory_high")[0]["server_name"] == "b"
    assert alerts(client, status="resolved") == []
    assert client.get("/api/alerts", params={"kind": "nope"}, headers=ADMIN).status_code == 422


def test_offline_detection_and_recovery(client, register, submit):
    server_id, token = register()
    submit(server_id, token)
    assert client.get(f"/api/servers/{server_id}/status", headers=ADMIN).json()["status"] == "healthy"

    # Pretend the agent's last report was two minutes ago
    with SessionLocal() as db:
        server = db.get(Server, server_id)
        server.last_seen_at = utcnow() - timedelta(minutes=2)
        db.commit()

    status = client.get(f"/api/servers/{server_id}/status", headers=ADMIN).json()
    assert status["status"] == "offline"
    assert status["seconds_since_last_seen"] > 90

    with SessionLocal() as db:
        assert evaluate_heartbeats(db, get_settings(), utcnow()) == 1
        assert evaluate_heartbeats(db, get_settings(), utcnow()) == 0  # no duplicate offline alert
        db.commit()

    offline = alerts(client, kind="server_offline")
    assert len(offline) == 1 and offline[0]["severity"] == "critical" and offline[0]["status"] == "open"

    # The agent comes back: the offline alert recovers
    submit(server_id, token)
    detail = client.get(f"/api/alerts/{offline[0]['id']}", headers=ADMIN).json()
    assert detail["status"] == "resolved" and detail["resolution"] == "recovered"
    assert client.get(f"/api/servers/{server_id}", headers=ADMIN).json()["status"] == "healthy"


def test_servers_that_never_reported_are_unknown_not_offline(client, register):
    server_id, _ = register()
    with SessionLocal() as db:
        assert evaluate_heartbeats(db, get_settings(), utcnow() + timedelta(days=1)) == 0
    assert client.get(f"/api/servers/{server_id}", headers=ADMIN).json()["status"] == "unknown"


def test_alert_activity_feed(client, register, submit):
    server_id, token = register()
    submit(server_id, token, cpu=99)
    submit(server_id, token, cpu=99)
    submit(server_id, token, cpu=10)
    events = client.get("/api/alert-events", headers=ADMIN).json()
    assert [e["event"] for e in events] == ["recovered", "opened"]
    assert events[0]["server_name"] == "web-01" and events[0]["kind"] == "cpu_high"
