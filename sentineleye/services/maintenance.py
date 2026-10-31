"""Periodic work: heartbeat (offline) checks and metric retention."""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import SessionLocal
from ..models import Metric
from ..notify import discard_pending, flush_pending
from ..timeutil import utcnow
from .alerts import evaluate_heartbeats

log = logging.getLogger("sentineleye.jobs")

RETENTION_EVERY = timedelta(hours=1)


def purge_old_metrics(db: Session, settings: Settings, now: datetime) -> int:
    cutoff = now - timedelta(days=settings.metric_retention_days)
    result = db.execute(delete(Metric).where(Metric.collected_at < cutoff))
    return result.rowcount or 0


def run_once(settings: Settings, now: datetime, purge: bool) -> None:
    with SessionLocal() as db:
        try:
            opened = evaluate_heartbeats(db, settings, now)
            purged = purge_old_metrics(db, settings, now) if purge else 0
            db.commit()
        except Exception:
            db.rollback()
            discard_pending()
            raise
    flush_pending()
    if opened:
        log.warning("%d server(s) marked offline", opened)
    if purged:
        log.info("Retention: removed %d metric rows older than %d days", purged, settings.metric_retention_days)


async def background_loop(settings: Settings) -> None:
    last_purge: datetime | None = None
    while True:
        now = utcnow()
        purge = last_purge is None or now - last_purge >= RETENTION_EVERY
        try:
            await asyncio.to_thread(run_once, settings, now, purge)
            if purge:
                last_purge = now
        except Exception:
            log.exception("Background job failed; retrying next cycle")
        await asyncio.sleep(settings.background_interval_seconds)
