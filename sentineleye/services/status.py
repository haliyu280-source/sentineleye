"""How a server's state is derived. Status is computed at read time so it can never go stale."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import THRESHOLD_KINDS, Alert, Metric, Server

# Maps each threshold alert kind to the metric column it watches
METRIC_FIELDS = {"cpu_high": "cpu_percent", "memory_high": "memory_percent", "disk_high": "disk_percent"}
METRIC_LABELS = {"cpu_high": "CPU", "memory_high": "Memory", "disk_high": "Disk"}


def effective_thresholds(server: Server, settings: Settings) -> dict[str, float]:
    return {
        "cpu_high": server.cpu_threshold or settings.default_cpu_threshold,
        "memory_high": server.memory_threshold or settings.default_memory_threshold,
        "disk_high": server.disk_threshold or settings.default_disk_threshold,
    }


def latest_metric(db: Session, server_id: int) -> Metric | None:
    return db.scalar(
        select(Metric).where(Metric.server_id == server_id).order_by(Metric.collected_at.desc()).limit(1)
    )


def active_alert_kinds(db: Session, server_id: int) -> set[str]:
    rows = db.scalars(
        select(Alert.kind).where(Alert.server_id == server_id, Alert.status != "resolved")
    ).all()
    return set(rows)


def is_offline(server: Server, now: datetime, settings: Settings) -> bool:
    return (
        server.last_seen_at is not None
        and (now - server.last_seen_at).total_seconds() > settings.heartbeat_timeout_seconds
    )


def server_status(
    server: Server,
    now: datetime,
    settings: Settings,
    latest: Metric | None,
    active_kinds: set[str],
) -> str:
    if not server.enabled:
        return "disabled"
    if server.last_seen_at is None:
        return "unknown"  # registered, but its agent has never reported
    if is_offline(server, now, settings):
        return "offline"
    if active_kinds & set(THRESHOLD_KINDS):
        return "warning"
    if latest is not None:
        limits = effective_thresholds(server, settings)
        # A breach still inside the grace period shows as a warning before an alert opens
        if any(getattr(latest, METRIC_FIELDS[k]) >= limits[k] for k in THRESHOLD_KINDS):
            return "warning"
    return "healthy"
