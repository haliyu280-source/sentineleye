"""Alert evaluation and lifecycle (open -> acknowledged -> resolved).

One active alert exists per server and kind. While a condition persists, the existing alert is
updated instead of new ones being created; when the metric drops back below the limit, the alert
is resolved with resolution "recovered".
"""

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import OFFLINE_KIND, Alert, AlertEvent, Metric, Server
from ..notify import queue_notification
from .status import METRIC_FIELDS, METRIC_LABELS, effective_thresholds, is_offline

log = logging.getLogger("sentineleye.alerts")


def active_alert(db: Session, server_id: int, kind: str) -> Alert | None:
    return db.scalar(
        select(Alert).where(Alert.server_id == server_id, Alert.kind == kind, Alert.status != "resolved")
    )


def _event(alert: Alert, event: str, actor: str, detail: str | None, at: datetime) -> AlertEvent:
    record = AlertEvent(event=event, actor=actor, detail=detail, at=at)
    alert.events.append(record)
    return record


def open_alert(
    db: Session,
    server: Server,
    kind: str,
    severity: str,
    message: str,
    now: datetime,
    *,
    threshold: float | None = None,
    value: float | None = None,
) -> Alert:
    alert = Alert(
        server_id=server.id,
        kind=kind,
        status="open",
        severity=severity,
        message=message,
        threshold=threshold,
        trigger_value=value,
        last_value=value,
        peak_value=value,
        opened_at=now,
        last_observed_at=now,
    )
    db.add(alert)
    _event(alert, "opened", "system", message, now)
    db.flush()
    log.warning("Alert opened: %s on %s (%s)", kind, server.name, message)
    queue_notification(alert, server, "opened")
    return alert


def resolve_alert(alert: Alert, server: Server, now: datetime, *, actor: str, resolution: str, detail: str | None):
    alert.status = "resolved"
    alert.resolved_at = now
    alert.resolution = resolution
    _event(alert, "recovered" if resolution == "recovered" else "resolved", actor, detail, now)
    log.info("Alert %s resolved (%s) on %s", alert.id, resolution, server.name)
    if resolution == "recovered":
        queue_notification(alert, server, "recovered")


def acknowledge_alert(alert: Alert, now: datetime, note: str | None) -> None:
    if alert.status != "open":
        raise ValueError(f"Only open alerts can be acknowledged (this one is {alert.status})")
    alert.status = "acknowledged"
    alert.acknowledged_at = now
    _event(alert, "acknowledged", "admin", note, now)


def manually_resolve(alert: Alert, server: Server, now: datetime, note: str | None) -> None:
    if alert.status == "resolved":
        raise ValueError("Alert is already resolved")
    resolve_alert(alert, server, now, actor="admin", resolution="manual", detail=note)


def evaluate_metric(db: Session, server: Server, metric: Metric, settings: Settings, now: datetime) -> None:
    """Apply one new metric sample to the server's threshold alerts and clear any offline alert."""
    limits = effective_thresholds(server, settings)
    needed = settings.alert_consecutive_breaches

    for kind, field in METRIC_FIELDS.items():
        value = getattr(metric, field)
        limit = limits[kind]
        label = METRIC_LABELS[kind]
        current = active_alert(db, server.id, kind)

        if value >= limit:
            if current:
                current.last_observed_at = now
                current.last_value = value
                current.peak_value = max(current.peak_value or value, value)
                continue
            # Grace period: require N consecutive breaching samples before opening an incident
            recent = db.scalars(
                select(Metric)
                .where(Metric.server_id == server.id)
                .order_by(Metric.collected_at.desc())
                .limit(needed)
            ).all()
            if len(recent) >= needed and all(getattr(m, field) >= limit for m in recent):
                open_alert(
                    db,
                    server,
                    kind,
                    "warning",
                    f"{label} at {value:.1f}% (limit {limit:g}%) for {needed} consecutive checks",
                    now,
                    threshold=limit,
                    value=value,
                )
        elif current:
            current.last_value = value
            resolve_alert(
                current,
                server,
                now,
                actor="system",
                resolution="recovered",
                detail=f"{label} back to {value:.1f}% (limit {limit:g}%)",
            )

    offline = active_alert(db, server.id, OFFLINE_KIND)
    if offline:
        resolve_alert(
            offline,
            server,
            now,
            actor="system",
            resolution="recovered",
            detail="Agent is reporting again",
        )


def evaluate_heartbeats(db: Session, settings: Settings, now: datetime) -> int:
    """Open an offline alert for every enabled server whose agent has gone quiet. Returns how many opened."""
    opened = 0
    servers = db.scalars(select(Server).where(Server.enabled.is_(True), Server.last_seen_at.is_not(None))).all()
    for server in servers:
        if not is_offline(server, now, settings) or active_alert(db, server.id, OFFLINE_KIND):
            continue
        silent = int((now - server.last_seen_at).total_seconds())
        open_alert(
            db,
            server,
            OFFLINE_KIND,
            "critical",
            f"No data from the agent for {silent}s (timeout {settings.heartbeat_timeout_seconds}s). "
            "The server is down, unreachable, or its agent has stopped.",
            now,
        )
        opened += 1
    return opened
