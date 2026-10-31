from datetime import timedelta

from conftest import ADMIN
from sentineleye.db import SessionLocal
from sentineleye.models import Metric
from sentineleye.timeutil import utcnow


def _insert_series(server_id, minutes_ago, cpu):
    """Writes metric rows directly to place them in the past (agents can only send recent samples)."""
    now = utcnow()
    gib = 1024**3
    with SessionLocal() as db:
        for minutes in minutes_ago:
            db.add(
                Metric(
                    server_id=server_id,
                    collected_at=now - timedelta(minutes=minutes),
                    received_at=now - timedelta(minutes=minutes),
                    cpu_percent=cpu,
                    memory_total_bytes=8 * gib,
                    memory_used_bytes=4 * gib,
                    memory_available_bytes=4 * gib,
                    memory_percent=50.0,
                    disk_total_bytes=100 * gib,
                    disk_used_bytes=60 * gib,
                    disk_available_bytes=40 * gib,
                    disk_percent=60.0,
                    uptime_seconds=1000.0,
                )
            )
        db.commit()


def history(client, server_id, range_key):
    response = client.get(f"/api/servers/{server_id}/metrics", params={"range": range_key}, headers=ADMIN)
    assert response.status_code == 200, response.text
    return response.json()


def test_ranges_filter_by_time(client, register):
    server_id, _ = register()
    _insert_series(server_id, [5, 30], cpu=10)  # within 1h
    _insert_series(server_id, [120, 300], cpu=20)  # within 6h
    _insert_series(server_id, [600], cpu=30)  # within 24h
    _insert_series(server_id, [3 * 24 * 60], cpu=40)  # within 7d
    _insert_series(server_id, [9 * 24 * 60], cpu=50)  # outside every range

    assert history(client, server_id, "1h")["raw_samples"] == 2
    assert history(client, server_id, "6h")["raw_samples"] == 4
    assert history(client, server_id, "24h")["raw_samples"] == 5
    week = history(client, server_id, "7d")
    assert week["raw_samples"] == 6
    assert week["bucket_seconds"] is None
    times = [p["t"] for p in week["points"]]
    assert times == sorted(times) and all(t.endswith("Z") for t in times)
    assert client.get(f"/api/servers/{server_id}/metrics", params={"range": "2y"}, headers=ADMIN).status_code == 422


def test_long_ranges_are_downsampled(client, register):
    server_id, _ = register()
    _insert_series(server_id, range(0, 1400, 2), cpu=40)  # 700 samples over ~23h
    day = history(client, server_id, "24h")
    assert day["raw_samples"] == 700
    assert day["bucket_seconds"] == 240
    assert len(day["points"]) <= 360
    assert sum(p["samples"] for p in day["points"]) == 700
    assert all(p["cpu"] == 40.0 for p in day["points"])


def test_latest_requires_a_report(client, register):
    server_id, _ = register()
    assert client.get(f"/api/servers/{server_id}/metrics/latest", headers=ADMIN).status_code == 404


def test_overview_counts_and_averages(client, register, submit):
    a_id, a_token = register("a")
    b_id, b_token = register("b")
    register("never-reported")
    submit(a_id, a_token, cpu=20, memory=40, disk=60)
    submit(b_id, b_token, cpu=90, memory=60, disk=80)

    body = client.get("/api/overview", headers=ADMIN).json()
    assert body["servers"] == {"total": 3, "healthy": 1, "warning": 1, "offline": 0, "unknown": 1, "disabled": 0}
    assert body["averages"] == {"cpu": 55.0, "memory": 50.0, "disk": 70.0, "reporting_servers": 2}
    assert body["alerts"] == {"open": 0, "acknowledged": 0}
