import os
import tempfile
from datetime import timedelta
from itertools import count

import pytest

# Configure the app before it is imported: throwaway database, known admin token, no background loop
_db_dir = tempfile.mkdtemp(prefix="sentineleye-tests-")
os.environ.update(
    {
        # SQLite by default; set SENTINELEYE_TEST_DATABASE_URL to run the suite against PostgreSQL
        "SENTINELEYE_DATABASE_URL": os.environ.get("SENTINELEYE_TEST_DATABASE_URL", f"sqlite:///{_db_dir}/test.db"),
        "SENTINELEYE_ADMIN_TOKEN": "test-admin-token",
        "SENTINELEYE_RUN_BACKGROUND_JOBS": "false",
        # Explicit values win over a developer's local .env
        "SENTINELEYE_PUBLIC_DASHBOARD": "false",
        "SENTINELEYE_ALERT_CONSECUTIVE_BREACHES": "2",
        "SENTINELEYE_HEARTBEAT_TIMEOUT_SECONDS": "90",
        "SENTINELEYE_SMTP_HOST": "",
    }
)

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from sentineleye.config import get_settings  # noqa: E402
from sentineleye.db import Base, engine  # noqa: E402
from sentineleye.security import rate_limiter  # noqa: E402
from sentineleye.timeutil import utcnow  # noqa: E402

ADMIN = {"Authorization": "Bearer test-admin-token"}


@pytest.fixture
def client():
    get_settings.cache_clear()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    rate_limiter.reset()
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def register(client):
    def _register(name="web-01", **extra):
        response = client.post("/api/servers", json={"name": name, **extra}, headers=ADMIN)
        assert response.status_code == 201, response.text
        body = response.json()
        return body["server"]["id"], body["agent_token"]["token"]

    return _register


@pytest.fixture
def sample():
    """Builds a valid agent payload. These are controlled test values, not live readings."""
    start = utcnow() - timedelta(seconds=250)
    ticks = count()

    def _sample(server_id, cpu=20.0, memory=40.0, disk=50.0, at=None, **extra):
        gib = 1024**3
        payload = {
            "server_id": server_id,
            # Strictly increasing timestamps inside the accepted clock-skew window
            "collected_at": (at or start + timedelta(milliseconds=500 * next(ticks))).isoformat(),
            "hostname": "test-host",
            "agent_version": "1.0.0",
            "os": {"name": "Ubuntu", "version": "24.04", "kernel": "6.8.0"},
            "uptime_seconds": 3600.0,
            "cpu_percent": cpu,
            "memory": {
                "total_bytes": 8 * gib,
                "used_bytes": int(8 * gib * memory / 100),
                "available_bytes": int(8 * gib * (1 - memory / 100)),
                "percent": memory,
            },
            "disk": {
                "mount": "/",
                "total_bytes": 100 * gib,
                "used_bytes": int(100 * gib * disk / 100),
                "available_bytes": int(100 * gib * (1 - disk / 100)),
                "percent": disk,
            },
        }
        payload.update(extra)
        return payload

    return _sample


def agent_headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def submit(client, sample):
    def _submit(server_id, token, **values):
        return client.post("/api/agent/metrics", json=sample(server_id, **values), headers=agent_headers(token))

    return _submit
