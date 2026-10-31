import io
import json
import urllib.error

import pytest

from sentineleye_agent.__main__ import Agent
from sentineleye_agent.client import BackendClient, DeliveryError, DeliveryResult
from sentineleye_agent.config import load_config

TOKEN = "se_0123456789abcdef_" + "B" * 43
CONFIG = load_config(
    {
        "SENTINELEYE_URL": "https://monitor.example.com",
        "SENTINELEYE_TOKEN": TOKEN,
        "SENTINELEYE_SERVER_ID": "5",
        "SENTINELEYE_MAX_RETRIES": "3",
        "SENTINELEYE_INTERVAL": "30",
    }
)


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def read(self, _n=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def http_error(code, detail="nope"):
    return urllib.error.HTTPError(
        CONFIG.metrics_url, code, "error", {}, io.BytesIO(json.dumps({"detail": detail}).encode())
    )


def client_with(*outcomes):
    """A BackendClient whose transport replays the given responses or exceptions in order."""
    seen = []
    queue = list(outcomes)

    def opener(request, timeout):
        seen.append(request)
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return BackendClient(CONFIG, opener=opener), seen


def test_successful_send_carries_auth_and_payload():
    client, seen = client_with(FakeResponse(202, {"accepted": True, "server_status": "healthy"}))
    result = client.send({"server_id": 5})
    assert result == DeliveryResult(status=202, server_status="healthy")
    request = seen[0]
    assert request.full_url == "https://monitor.example.com/api/agent/metrics"
    assert request.get_header("Authorization") == f"Bearer {TOKEN}"
    assert json.loads(request.data) == {"server_id": 5}


@pytest.mark.parametrize(
    "error, retryable",
    [
        (http_error(401, "Invalid, revoked or expired agent token"), False),
        (http_error(403), False),
        (http_error(422, [{"msg": "cpu_percent too large"}]), False),
        (http_error(429), True),
        (http_error(503), True),
        (urllib.error.URLError("Connection refused"), True),
        (TimeoutError("timed out"), True),
    ],
)
def test_errors_are_classified(error, retryable):
    client, _ = client_with(error)
    with pytest.raises(DeliveryError) as caught:
        client.send({})
    assert caught.value.retryable is retryable


def test_validation_error_messages_are_readable():
    client, _ = client_with(http_error(422, [{"msg": "cpu_percent too large"}]))
    with pytest.raises(DeliveryError, match="cpu_percent too large"):
        client.send({})


@pytest.mark.parametrize("response", [FakeResponse(200, b"<html>proxy</html>"), FakeResponse(200, {"accepted": False})])
def test_invalid_backend_responses_are_errors(response):
    client, _ = client_with(response)
    with pytest.raises(DeliveryError):
        client.send({})


class StaticCollector:
    def collect(self, server_id):
        return {
            "server_id": server_id,
            "cpu_percent": 10.0,
            "uptime_seconds": 1.0,
            "memory": {"total_bytes": 10, "used_bytes": 5, "available_bytes": 5, "percent": 50.0},
            "disk": {"total_bytes": 10, "used_bytes": 5, "available_bytes": 5, "percent": 50.0},
        }


def make_agent(*outcomes):
    sleeps = []
    client, seen = client_with(*outcomes)
    agent = Agent(CONFIG, collector=StaticCollector(), client=client, sleep=sleeps.append)
    return agent, seen, sleeps


def test_network_failures_are_retried_and_reported_on_success():
    agent, seen, sleeps = make_agent(
        urllib.error.URLError("refused"),
        http_error(503),
        FakeResponse(202, {"accepted": True}),
    )
    assert agent.run_once() is True
    assert len(seen) == 3
    assert len(sleeps) == 2 and sleeps[0] < sleeps[1]  # exponential backoff
    last_payload = json.loads(seen[-1].data)
    assert last_payload["delivery"]["failed_attempts"] == 2
    assert "HTTP 503" in last_payload["delivery"]["last_error"]
    assert agent.failed_attempts == 0 and agent.last_error is None


def test_gives_up_after_max_retries_and_keeps_the_failure_count():
    agent, seen, sleeps = make_agent(*[urllib.error.URLError("down")] * 4)
    assert agent.run_once() is False
    assert len(seen) == 4  # first try + 3 retries
    assert agent.failed_attempts == 4

    # The next cycle reports the backlog of failures
    agent.client, seen = client_with(FakeResponse(202, {"accepted": True}))
    assert agent.run_once() is True
    assert json.loads(seen[0].data)["delivery"]["failed_attempts"] == 4


def test_authentication_failures_are_not_retried():
    agent, seen, sleeps = make_agent(http_error(401))
    assert agent.run_once() is False
    assert len(seen) == 1 and sleeps == []
    assert "HTTP 401" in agent.last_error


def test_duplicate_sample_is_skipped_without_counting_as_failure():
    agent, seen, _ = make_agent(http_error(409))
    assert agent.run_once() is False
    assert agent.failed_attempts == 0


def test_backoff_never_exceeds_half_the_interval():
    agent, _, _ = make_agent()
    assert all(agent.backoff(n) <= CONFIG.interval_seconds / 2 for n in range(10))
    assert agent.backoff(0) < agent.backoff(3)
