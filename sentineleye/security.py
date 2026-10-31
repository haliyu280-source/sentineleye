"""Agent tokens, admin authentication and simple in-process rate limiting.

Agent tokens look like ``se_<token_id>_<secret>``. The token id is public and used for lookup;
only a SHA-256 hash of the secret is stored. Secrets are 256-bit random values, so a fast hash
is appropriate here (there is nothing to brute-force, unlike a human password).
"""

import hashlib
import hmac
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .db import get_db
from .models import AgentToken, Server
from .timeutil import utcnow

TOKEN_PATTERN = re.compile(r"^se_([0-9a-f]{16})_([A-Za-z0-9_-]{43})$")


@dataclass(frozen=True)
class IssuedToken:
    token: str  # full value, shown to the operator exactly once
    token_id: str
    secret_hash: str


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def generate_agent_token() -> IssuedToken:
    token_id = secrets.token_hex(8)
    secret = secrets.token_urlsafe(32)
    return IssuedToken(token=f"se_{token_id}_{secret}", token_id=token_id, secret_hash=hash_secret(secret))


def issue_token(db: Session, server: Server, settings: Settings) -> IssuedToken:
    issued = generate_agent_token()
    expires_at = utcnow() + timedelta(days=settings.token_ttl_days) if settings.token_ttl_days else None
    db.add(
        AgentToken(
            server_id=server.id,
            token_id=issued.token_id,
            secret_hash=issued.secret_hash,
            expires_at=expires_at,
        )
    )
    return issued


class RateLimiter:
    """Sliding one-minute window per key. In-process only, so it applies per backend instance."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


rate_limiter = RateLimiter()


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_admin(
    request: Request,
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.admin_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Management API is disabled. Set SENTINELEYE_ADMIN_TOKEN on the backend.",
        )

    supplied = _bearer(authorization)
    # Compare digests so neither the value nor its length leaks through timing
    if supplied and hmac.compare_digest(hash_secret(supplied), hash_secret(settings.admin_token)):
        return

    if not rate_limiter.allow(f"admin-fail:{_client_key(request)}", settings.admin_auth_failures_per_minute):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many failed attempts")
    raise _unauthorized("Missing or invalid admin token")


def authenticate_agent(
    request: Request,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AgentToken:
    supplied = _bearer(authorization)
    match = TOKEN_PATTERN.match(supplied or "")
    if not match:
        if not rate_limiter.allow(f"agent-fail:{_client_key(request)}", settings.admin_auth_failures_per_minute):
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many failed attempts")
        raise _unauthorized("Missing or malformed agent token")

    token_id, secret = match.groups()
    record = db.scalar(select(AgentToken).where(AgentToken.token_id == token_id))
    valid = record is not None and hmac.compare_digest(record.secret_hash, hash_secret(secret))
    now = utcnow()

    if not valid or record.revoked_at is not None or (record.expires_at and record.expires_at <= now):
        if not rate_limiter.allow(f"agent-fail:{_client_key(request)}", settings.admin_auth_failures_per_minute):
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many failed attempts")
        # Same message for unknown, wrong, revoked and expired tokens
        raise _unauthorized("Invalid, revoked or expired agent token")

    if not record.server.enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This server is disabled")

    if not rate_limiter.allow(f"agent:{token_id}", settings.agent_rate_limit_per_minute):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Agent is reporting too often",
            headers={"Retry-After": "60"},
        )

    record.last_used_at = now
    return record
