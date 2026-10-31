"""Full flow with the real agent code talking to the real backend.

The agent reads /proc-format files that the test writes, so the metric values are controlled
test inputs, not readings from this machine. Everything else (configuration, parsing, HTTP
payloads, authentication, persistence, alerting) runs unmodified.
"""

import io
import urllib.error
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import func, select

from conftest import ADMIN
from sentineleye.config import get_settings
from sentineleye.db import SessionLocal
from sentineleye.models import Metric, Server
from sentineleye.services.alerts import evaluate_heartbeats
from sentineleye.timeutil import utcnow
from sentineleye_agent.__main__ import Agent
from sentineleye_agent.client import BackendClient
from sentineleye_agent.collector import Collector, read_cpu_times
from sentineleye_agent.config import load_config

FIXTURES = Path(__file__).parents[1] / "agent" / "tests" / "fixtures"


class InProcessTransport:
    """Stands in for urllib's network layer and routes the agent's request into the FastAPI app."""

    def __init__(self, client):
        self.client = client

    def __call__(self, request, timeout):
        path = request.full_url.split("://", 1)[1].split("/", 1)[1]
        response = self.client.post("/" + path, content=request.data, headers=dict(request.header_items()))
        if response.status_code >= 400:
            raise urllib.error.HTTPError(request.full_url, response.status_code, "error", {}, io.BytesIO(response.content))
        return _Response(response.status_code, response.content)


class _Response:
    def __init__(self, status, content):
        self.status = status
        self._content = content

    def read(self, _n=-1):
        return self._content

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ControlledHost:
    """A fake /proc tree whose CPU and memory readings the test sets explicitly."""

    def __init__(self, root: Path):
        self.proc = root / "proc"
        self.proc.mkdir(parents=True)
        for name in ("stat", "meminfo", "uptime"):
            (self.proc / name).write_text((FIXTURES / "proc" / name).read_text())
        self.collector = Collector(
            proc_root=self.proc,
            etc_root=FIXTURES / "etc",
            statvfs=lambda _p: SimpleNamespace(f_blocks=1000, f_bfree=500, f_bavail=500, f_frsize=4096),
            first_sample_seconds=0,
        )
        self.collector._last_cpu = read_cpu_times(self.proc)

    def set(self, cpu: float, memory: float = 40.0) -> None:
        before = read_cpu_times(self.proc)
        step = 1000
        busy = round(step * cpu / 100)
        user = before.total - before.idle + busy
        idle = before.idle + step - busy
        (self.proc / "stat").write_text(f"cpu  {user} 0 0 {idle} 0 0 0 0 0 0\n")
        total_kib = 8_000_000
        available = round(total_kib * (1 - memory / 100))
        (self.proc / "meminfo").write_text(f"MemTotal: {total_kib} kB\nMemAvailable: {available} kB\n")


def make_agent(client, server_id, token, root):
    config = load_config(
        {
            "SENTINELEYE_URL": "http://testserver",
            "SENTINELEYE_ALLOW_HTTP": "true",
            "SENTINELEYE_TOKEN": token,
            "SENTINELEYE_SERVER_ID": str(server_id),
            "SENTINELEYE_MAX_RETRIES": "0",
        }
    )
    host = ControlledHost(root)
    backend = BackendClient(config, opener=InProcessTransport(client))
    return Agent(config, collector=host.collector, client=backend, sleep=lambda s: None), host


def test_register_configure_report_alert_recover_and_go_offline(client, tmp_path):
    # 1-2. Register a server and receive its token
    created = client.post("/api/servers", json={"name": "app-01"}, headers=ADMIN).json()
    server_id, token = created["server"]["id"], created["agent_token"]["token"]

    # 3-4. Configure the real agent and send a normal sample
    agent, host = make_agent(client, server_id, token, tmp_path)
    host.set(cpu=25, memory=40)
    assert agent.run_once() is True

    # 5. Database records
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Metric).where(Metric.server_id == server_id)) == 1
        server = db.get(Server, server_id)
        assert server.os_name == "Ubuntu" and server.agent_version == "1.0.0"

    # 6. Retrieve through the API
    detail = client.get(f"/api/servers/{server_id}", headers=ADMIN).json()
    assert detail["status"] == "healthy"
    assert detail["latest"]["cpu_percent"] == 25.0
    assert detail["latest"]["memory_percent"] == 40.0

    # 7. Exceed the CPU threshold for two consecutive checks
    host.set(cpu=92)
    agent.run_once()
    host.set(cpu=95)
    agent.run_once()
    active = client.get("/api/alerts", params={"status": "active"}, headers=ADMIN).json()
    assert [(a["kind"], a["trigger_value"]) for a in active] == [("cpu_high", 95.0)]

    # 8. Recovery
    host.set(cpu=30)
    agent.run_once()
    resolved = client.get(f"/api/alerts/{active[0]['id']}", headers=ADMIN).json()
    assert resolved["status"] == "resolved" and resolved["resolution"] == "recovered"

    # 9. Heartbeats stop: evaluate as if 5 minutes have passed
    with SessionLocal() as db:
        assert evaluate_heartbeats(db, get_settings(), utcnow() + timedelta(minutes=5)) == 1
        db.commit()
    offline = client.get("/api/alerts", params={"kind": "server_offline"}, headers=ADMIN).json()
    assert offline[0]["status"] == "open"

    # Agent resumes; the outage is recorded as recovered
    host.set(cpu=20)
    agent.run_once()
    offline = client.get(f"/api/alerts/{offline[0]['id']}", headers=ADMIN).json()
    assert offline["resolution"] == "recovered"

    history = client.get(f"/api/servers/{server_id}/metrics", params={"range": "1h"}, headers=ADMIN).json()
    assert [round(p["cpu"]) for p in history["points"]] == [25, 92, 95, 30, 20]


def test_multiple_agents_keep_separate_identities(client, tmp_path):
    first = client.post("/api/servers", json={"name": "node-a"}, headers=ADMIN).json()
    second = client.post("/api/servers", json={"name": "node-b"}, headers=ADMIN).json()
    agent_a, host_a = make_agent(client, first["server"]["id"], first["agent_token"]["token"], tmp_path / "a")
    agent_b, host_b = make_agent(client, second["server"]["id"], second["agent_token"]["token"], tmp_path / "b")
    host_a.set(cpu=10)
    host_b.set(cpu=60)
    assert agent_a.run_once() and agent_b.run_once()

    servers = {s["name"]: s for s in client.get("/api/servers", headers=ADMIN).json()}
    assert servers["node-a"]["latest"]["cpu_percent"] == 10.0
    assert servers["node-b"]["latest"]["cpu_percent"] == 60.0

    # Agent A misconfigured with B's id is refused
    impostor, host = make_agent(client, second["server"]["id"], first["agent_token"]["token"], tmp_path / "c")
    host.set(cpu=10)
    assert impostor.run_once() is False
    assert "HTTP 403" in impostor.last_error
