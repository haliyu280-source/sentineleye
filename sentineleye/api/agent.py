import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..models import AgentToken, Metric
from ..notify import discard_pending, flush_pending
from ..schemas import MetricSubmission, SubmissionAccepted
from ..security import authenticate_agent
from ..services.alerts import evaluate_metric
from ..services.status import active_alert_kinds, latest_metric, server_status
from ..timeutil import as_utc, utcnow

log = logging.getLogger("sentineleye.agent")

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.post("/metrics", response_model=SubmissionAccepted, status_code=status.HTTP_202_ACCEPTED)
def submit_metrics(
    body: MetricSubmission,
    token: AgentToken = Depends(authenticate_agent),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Accept one metric sample from an authenticated agent. Agents can only report for their own server."""
    server = token.server
    if body.server_id != server.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Token is not valid for this server_id")

    now = utcnow()
    collected_at = as_utc(body.collected_at)
    skew = timedelta(seconds=settings.max_clock_skew_seconds)
    if collected_at > now + skew:
        raise HTTPException(status_code=422, detail="collected_at is in the future; check the agent's clock")
    if collected_at < now - skew:
        raise HTTPException(status_code=422, detail="collected_at is too old; stale samples are not accepted")

    previous = latest_metric(db, server.id)
    if previous is not None and collected_at <= previous.collected_at:
        raise HTTPException(status_code=409, detail="Sample is not newer than the last one received (duplicate or replay)")

    metric = Metric(
        server_id=server.id,
        collected_at=collected_at,
        received_at=now,
        cpu_percent=body.cpu_percent,
        memory_total_bytes=body.memory.total_bytes,
        memory_used_bytes=body.memory.used_bytes,
        memory_available_bytes=body.memory.available_bytes,
        memory_percent=body.memory.percent,
        disk_total_bytes=body.disk.total_bytes,
        disk_used_bytes=body.disk.used_bytes,
        disk_available_bytes=body.disk.available_bytes,
        disk_percent=body.disk.percent,
        uptime_seconds=body.uptime_seconds,
    )
    db.add(metric)

    server.hostname = body.hostname
    server.os_name = body.os.name
    server.os_version = body.os.version or None
    server.kernel = body.os.kernel or None
    server.agent_version = body.agent_version
    server.uptime_seconds = body.uptime_seconds
    server.first_seen_at = server.first_seen_at or now
    server.last_seen_at = now
    # The agent reports how many deliveries failed before this one got through
    server.failed_deliveries = body.delivery.failed_attempts
    server.last_agent_error = body.delivery.last_error
    if body.delivery.failed_attempts:
        log.info("Server %s recovered after %d failed deliveries", server.name, body.delivery.failed_attempts)

    try:
        db.flush()
        evaluate_metric(db, server, metric, settings, now)
        db.commit()
    except Exception:
        db.rollback()
        discard_pending()
        raise
    flush_pending()

    kinds = active_alert_kinds(db, server.id)
    return SubmissionAccepted(server_status=server_status(server, now, settings, metric, kinds))
