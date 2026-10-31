from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..models import ALERT_KINDS, Alert, AlertEvent
from ..notify import flush_pending
from ..schemas import ActivityOut, AlertActionIn, AlertDetail, AlertEventOut, AlertOut
from ..security import require_admin, viewer_access
from ..services.alerts import acknowledge_alert, manually_resolve
from ..timeutil import utcnow
from .serializers import alert_fields, alert_out

router = APIRouter(prefix="/api", tags=["alerts"])

StatusFilter = Literal["open", "acknowledged", "resolved", "active", "all"]


def _get_alert(db: Session, alert_id: int) -> Alert:
    alert = db.get(Alert, alert_id, options=[joinedload(Alert.server)])
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    return alert


def _detail(alert: Alert) -> AlertDetail:
    return AlertDetail(
        **alert_fields(alert),
        events=[AlertEventOut.model_validate(e) for e in alert.events],
    )


@router.get("/alerts", dependencies=[Depends(viewer_access)], response_model=list[AlertOut])
def list_alerts(
    status_filter: StatusFilter = Query("all", alias="status", description="'active' means open or acknowledged"),
    server_id: int | None = None,
    kind: str | None = Query(None, description=f"One of: {', '.join(ALERT_KINDS)}"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = select(Alert).options(joinedload(Alert.server)).order_by(Alert.opened_at.desc()).limit(limit)
    if status_filter == "active":
        query = query.where(Alert.status != "resolved")
    elif status_filter != "all":
        query = query.where(Alert.status == status_filter)
    if server_id is not None:
        query = query.where(Alert.server_id == server_id)
    if kind is not None:
        if kind not in ALERT_KINDS:
            raise HTTPException(status_code=422, detail=f"kind must be one of {', '.join(ALERT_KINDS)}")
        query = query.where(Alert.kind == kind)
    return [alert_out(a) for a in db.scalars(query).all()]


@router.get("/alerts/{alert_id}", dependencies=[Depends(viewer_access)], response_model=AlertDetail)
def get_alert(alert_id: int, db: Session = Depends(get_db)):
    return _detail(_get_alert(db, alert_id))


@router.post("/alerts/{alert_id}/acknowledge", dependencies=[Depends(require_admin)], response_model=AlertDetail)
def acknowledge(alert_id: int, body: AlertActionIn | None = None, db: Session = Depends(get_db)):
    alert = _get_alert(db, alert_id)
    try:
        acknowledge_alert(alert, utcnow(), body.note if body else None)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    db.commit()
    return _detail(alert)


@router.post("/alerts/{alert_id}/resolve", dependencies=[Depends(require_admin)], response_model=AlertDetail)
def resolve(alert_id: int, body: AlertActionIn | None = None, db: Session = Depends(get_db)):
    alert = _get_alert(db, alert_id)
    try:
        manually_resolve(alert, alert.server, utcnow(), body.note if body else None)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    db.commit()
    flush_pending()
    return _detail(alert)


@router.get("/alert-events", dependencies=[Depends(viewer_access)], response_model=list[ActivityOut])
def recent_activity(
    server_id: int | None = None,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Alert history across all servers, newest first: openings, acknowledgements, recoveries and resolutions."""
    query = (
        select(AlertEvent)
        .join(AlertEvent.alert)
        .options(joinedload(AlertEvent.alert).joinedload(Alert.server))
        .order_by(AlertEvent.at.desc(), AlertEvent.id.desc())
        .limit(limit)
    )
    if server_id is not None:
        query = query.where(Alert.server_id == server_id)
    return [
        ActivityOut(
            **AlertEventOut.model_validate(e).model_dump(),
            server_id=e.alert.server_id,
            server_name=e.alert.server.name,
            kind=e.alert.kind,
        )
        for e in db.scalars(query).all()
    ]
