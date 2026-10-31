"""Agent configuration from environment variables, optionally loaded from a KEY=VALUE file.

The systemd unit points at /etc/sentineleye-agent/agent.env, which uses the same format.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

TOKEN_PATTERN = re.compile(r"^se_[0-9a-f]{16}_[A-Za-z0-9_-]{43}$")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class AgentConfig:
    backend_url: str
    token: str
    server_id: int
    interval_seconds: int = 30
    timeout_seconds: float = 10.0
    max_retries: int = 4
    disk_path: str = "/"
    ca_bundle: str | None = None

    @property
    def metrics_url(self) -> str:
        return self.backend_url.rstrip("/") + "/api/agent/metrics"

    def __repr__(self) -> str:  # never print the token, even by accident
        return (
            f"AgentConfig(backend_url={self.backend_url!r}, server_id={self.server_id}, "
            f"interval_seconds={self.interval_seconds}, token=<redacted>)"
        )


def read_env_file(path: str | Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, raw in enumerate(Path(path).read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            raise ConfigError(f"{path}:{number}: expected KEY=VALUE")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _int(values: dict, key: str, default: int, low: int, high: int) -> int:
    raw = values.get(key)
    if raw in (None, ""):
        return default
    try:
        number = int(raw)
    except ValueError:
        raise ConfigError(f"{key} must be a whole number") from None
    if not low <= number <= high:
        raise ConfigError(f"{key} must be between {low} and {high}")
    return number


def load_config(env: dict[str, str] | None = None, config_file: str | None = None) -> AgentConfig:
    values = dict(os.environ if env is None else env)
    if config_file:
        # Values already in the environment win over the file
        values = {**read_env_file(config_file), **values}

    url = values.get("SENTINELEYE_URL", "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ConfigError("SENTINELEYE_URL must be a full URL, e.g. https://sentineleye.example.com")
    allow_http = values.get("SENTINELEYE_ALLOW_HTTP", "").lower() in ("1", "true", "yes")
    if parsed.scheme == "http" and parsed.hostname not in LOCAL_HOSTS and not allow_http:
        raise ConfigError(
            "Refusing to send the agent token over plain HTTP. Use https://, "
            "or set SENTINELEYE_ALLOW_HTTP=true for an isolated test network."
        )

    token = values.get("SENTINELEYE_TOKEN", "").strip()
    if not TOKEN_PATTERN.match(token):
        raise ConfigError("SENTINELEYE_TOKEN is missing or not a valid agent token (se_<id>_<secret>)")

    raw_id = values.get("SENTINELEYE_SERVER_ID", "").strip()
    if not raw_id.isdigit() or int(raw_id) <= 0:
        raise ConfigError("SENTINELEYE_SERVER_ID must be the numeric id shown when the server was registered")

    ca_bundle = values.get("SENTINELEYE_CA_BUNDLE") or None
    if ca_bundle and not Path(ca_bundle).is_file():
        raise ConfigError(f"SENTINELEYE_CA_BUNDLE points to a missing file: {ca_bundle}")

    return AgentConfig(
        backend_url=url,
        token=token,
        server_id=int(raw_id),
        interval_seconds=_int(values, "SENTINELEYE_INTERVAL", 30, 5, 3600),
        timeout_seconds=float(_int(values, "SENTINELEYE_TIMEOUT", 10, 1, 120)),
        max_retries=_int(values, "SENTINELEYE_MAX_RETRIES", 4, 0, 10),
        disk_path=values.get("SENTINELEYE_DISK_PATH", "/") or "/",
        ca_bundle=ca_bundle,
    )
