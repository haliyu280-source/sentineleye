from datetime import datetime

from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Alert, Server
from ..schemas import AlertOut, EffectiveThresholds, MetricOut, ServerOut, Thresholds
from ..services.status import active_alert_kinds, effective_thresholds, latest_metric, server_status


def server_out(db: Session, server: Server, settings: Settings, now: datetime, private: bool = True) -> ServerOut:
    """`private=False` is the public view: the agent's raw error text can name internal hosts, so it is left out."""
    latest = latest_metric(db, server.id)
    kinds = active_alert_kinds(db, server.id)
    limits = effective_thresholds(server, settings)
    return ServerOut(
        id=server.id,
        name=server.name,
        description=server.description,
        environment=server.environment,
        enabled=server.enabled,
        status=server_status(server, now, settings, latest, kinds),
        hostname=server.hostname,
        os_name=server.os_name,
        os_version=server.os_version,
        kernel=server.kernel,
        agent_version=server.agent_version,
        uptime_seconds=server.uptime_seconds,
        failed_deliveries=server.failed_deliveries,
        last_agent_error=server.last_agent_error if private else None,
        thresholds=EffectiveThresholds(
            cpu=limits["cpu_high"], memory=limits["memory_high"], disk=limits["disk_high"]
        ),
        threshold_overrides=Thresholds(
            cpu=server.cpu_threshold, memory=server.memory_threshold, disk=server.disk_threshold
        ),
        created_at=server.created_at,
        first_seen_at=server.first_seen_at,
        last_seen_at=server.last_seen_at,
        latest=MetricOut.model_validate(latest) if latest else None,
        active_alerts=len(kinds),
    )


def alert_fields(alert: Alert) -> dict:
    fields = {name: getattr(alert, name) for name in AlertOut.model_fields if name != "server_name"}
    return {**fields, "server_name": alert.server.name}


def alert_out(alert: Alert) -> AlertOut:
    return AlertOut(**alert_fields(alert))
