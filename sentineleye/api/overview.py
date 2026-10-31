from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..models import Alert, Server
from ..schemas import Averages, OverviewOut
from ..security import require_admin
from ..timeutil import utcnow
from .serializers import server_out

router = APIRouter(prefix="/api", tags=["monitoring"], dependencies=[Depends(require_admin)])


@router.get("/overview", response_model=OverviewOut)
def overview(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    """Fleet-wide counts and averages, computed from each server's latest real sample."""
    now = utcnow()
    servers = [server_out(db, s, settings, now) for s in db.scalars(select(Server)).all()]

    counts = {"total": len(servers), "healthy": 0, "warning": 0, "offline": 0, "unknown": 0, "disabled": 0}
    for s in servers:
        counts[s.status] += 1

    # Averages only include servers that are currently reporting
    reporting = [s.latest for s in servers if s.latest and s.status in ("healthy", "warning")]

    def avg(field: str) -> float | None:
        return round(sum(getattr(m, field) for m in reporting) / len(reporting), 2) if reporting else None

    alert_counts = dict(
        db.execute(select(Alert.status, func.count()).where(Alert.status != "resolved").group_by(Alert.status)).all()
    )
    return OverviewOut(
        generated_at=now,
        servers=counts,
        averages=Averages(
            cpu=avg("cpu_percent"),
            memory=avg("memory_percent"),
            disk=avg("disk_percent"),
            reporting_servers=len(reporting),
        ),
        alerts={"open": alert_counts.get("open", 0), "acknowledged": alert_counts.get("acknowledged", 0)},
        heartbeat_timeout_seconds=settings.heartbeat_timeout_seconds,
    )
