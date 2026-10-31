"""Sends samples to the central backend over HTTP(S) using urllib."""

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import __version__
from .config import AgentConfig


class DeliveryError(Exception):
    """A send failed. `retryable` says whether trying again might help."""

    def __init__(self, message: str, *, retryable: bool, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


@dataclass(frozen=True)
class DeliveryResult:
    status: int
    server_status: str | None


def _detail(raw: bytes) -> str:
    try:
        detail = json.loads(raw).get("detail")
        if isinstance(detail, list):  # FastAPI validation errors
            return "; ".join(str(d.get("msg", d)) for d in detail)[:300]
        return str(detail)[:300]
    except (ValueError, AttributeError):
        return raw[:200].decode(errors="replace")


class BackendClient:
    def __init__(self, config: AgentConfig, opener=None):
        self.config = config
        context = ssl.create_default_context(cafile=config.ca_bundle) if config.ca_bundle else None
        self._urlopen = opener or (lambda req, timeout: urllib.request.urlopen(req, timeout=timeout, context=context))

    def send(self, sample: dict) -> DeliveryResult:
        request = urllib.request.Request(
            self.config.metrics_url,
            data=json.dumps(sample).encode(),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.config.token}",
                "Content-Type": "application/json",
                "User-Agent": f"sentineleye-agent/{__version__}",
            },
        )
        try:
            with self._urlopen(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read(65536)
                status = response.status
        except urllib.error.HTTPError as err:
            message = f"HTTP {err.code}: {_detail(err.read(65536))}"
            # 429 and 5xx are worth retrying; auth and validation problems are not
            raise DeliveryError(message, retryable=err.code == 429 or err.code >= 500, status=err.code) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as err:
            reason = getattr(err, "reason", err)
            raise DeliveryError(f"Cannot reach backend: {reason}", retryable=True) from None

        try:
            body = json.loads(raw)
        except ValueError:
            raise DeliveryError("Backend returned a response that is not JSON", retryable=True, status=status) from None
        if not isinstance(body, dict) or body.get("accepted") is not True:
            raise DeliveryError("Backend did not confirm the sample was accepted", retryable=True, status=status)
        return DeliveryResult(status=status, server_status=body.get("server_status"))
