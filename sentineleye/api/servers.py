from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..models import AgentToken, Server
from ..schemas import (
    HistoryOut,
    HistoryRange,
    IssuedTokenOut,
    MetricOut,
    ServerCreate,
    ServerCreated,
    ServerOut,
    ServerStatusOut,
    ServerUpdate,
    TokenOut,
)
from ..security import issue_token, require_admin, viewer_access
from ..services.history import metric_history
from ..services.status import active_alert_kinds, latest_metric, server_status
from ..timeutil import utcnow
from .serializers import server_out

router = APIRouter(prefix="/api/servers", tags=["servers"])

# Reads are open to anonymous viewers when SENTINELEYE_PUBLIC_DASHBOARD is on; changes never are
admin_only = [Depends(require_admin)]


def get_server_or_404(db: Session, server_id: int) -> Server:
    server = db.get(Server, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Server not found")
    return server


def _name_taken() -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A server with that name already exists")


@router.post("", dependencies=admin_only, response_model=ServerCreated, status_code=status.HTTP_201_CREATED)
def register_server(
    body: ServerCreate, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
):
    """Register a server and issue its first agent token. The token is only returned here."""
    server = Server(
        name=body.name.strip(),
        description=body.description,
        environment=body.environment,
        cpu_threshold=body.thresholds.cpu,
        memory_threshold=body.thresholds.memory,
        disk_threshold=body.thresholds.disk,
    )
    db.add(server)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise _name_taken() from None
    issued = issue_token(db, server, settings)
    db.commit()
    return ServerCreated(
        server=server_out(db, server, settings, utcnow()),
        agent_token=IssuedTokenOut(server_id=server.id, token_id=issued.token_id, token=issued.token),
    )


@router.get("", response_model=list[ServerOut])
def list_servers(
    include_disabled: bool = True,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    is_admin: bool = Depends(viewer_access),
):
    query = select(Server).order_by(Server.name)
    if not include_disabled:
        query = query.where(Server.enabled.is_(True))
    now = utcnow()
    return [server_out(db, s, settings, now, private=is_admin) for s in db.scalars(query).all()]


@router.get("/{server_id}", response_model=ServerOut)
def get_server(
    server_id: int,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    is_admin: bool = Depends(viewer_access),
):
    return server_out(db, get_server_or_404(db, server_id), settings, utcnow(), private=is_admin)


@router.patch("/{server_id}", dependencies=admin_only, response_model=ServerOut)
def update_server(
    server_id: int, body: ServerUpdate, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
):
    server = get_server_or_404(db, server_id)
    changes = body.model_dump(exclude_unset=True)
    for field in ("name", "description", "environment", "enabled"):
        if field in changes:
            if field == "name" and changes[field] is None:
                raise HTTPException(status_code=422, detail="name cannot be null")
            setattr(server, field, changes[field].strip() if field == "name" else changes[field])
    if "thresholds" in changes and body.thresholds is not None:
        for key, value in body.thresholds.model_dump(exclude_unset=True).items():
            setattr(server, f"{key}_threshold", value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _name_taken() from None
    return server_out(db, server, settings, utcnow())


@router.delete("/{server_id}", dependencies=admin_only, status_code=status.HTTP_204_NO_CONTENT)
def delete_server(server_id: int, db: Session = Depends(get_db)):
    """Permanently remove a server with its tokens, metric history and alerts. Use PATCH enabled=false to keep history."""
    db.delete(get_server_or_404(db, server_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------- Tokens ----------


@router.get("/{server_id}/tokens", dependencies=admin_only, response_model=list[TokenOut])
def list_tokens(server_id: int, db: Session = Depends(get_db)):
    server = get_server_or_404(db, server_id)
    return sorted(server.tokens, key=lambda t: t.created_at, reverse=True)


@router.post("/{server_id}/tokens", dependencies=admin_only, response_model=IssuedTokenOut, status_code=status.HTTP_201_CREATED)
def issue_additional_token(server_id: int, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    """Issue an extra token without revoking existing ones (e.g. for a staged agent migration)."""
    server = get_server_or_404(db, server_id)
    issued = issue_token(db, server, settings)
    db.commit()
    return IssuedTokenOut(server_id=server.id, token_id=issued.token_id, token=issued.token)


@router.post("/{server_id}/tokens/reissue", dependencies=admin_only, response_model=IssuedTokenOut, status_code=status.HTTP_201_CREATED)
def reissue_token(server_id: int, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    """Revoke every active token for the server and issue a single replacement."""
    server = get_server_or_404(db, server_id)
    now = utcnow()
    for token in server.tokens:
        if token.revoked_at is None:
            token.revoked_at = now
    issued = issue_token(db, server, settings)
    db.commit()
    return IssuedTokenOut(server_id=server.id, token_id=issued.token_id, token=issued.token)


@router.post("/{server_id}/tokens/{token_id}/revoke", dependencies=admin_only, response_model=TokenOut)
def revoke_token(server_id: int, token_id: str, db: Session = Depends(get_db)):
    get_server_or_404(db, server_id)
    token = db.scalar(
        select(AgentToken).where(AgentToken.server_id == server_id, AgentToken.token_id == token_id)
    )
    if token is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found for this server")
    if token.revoked_at is None:
        token.revoked_at = utcnow()
        db.commit()
    return token


# ---------- Monitoring ----------


@router.get("/{server_id}/status", dependencies=[Depends(viewer_access)], response_model=ServerStatusOut)
def get_server_status(server_id: int, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    server = get_server_or_404(db, server_id)
    now = utcnow()
    kinds = active_alert_kinds(db, server.id)
    return ServerStatusOut(
        server_id=server.id,
        status=server_status(server, now, settings, latest_metric(db, server.id), kinds),
        last_seen_at=server.last_seen_at,
        seconds_since_last_seen=(now - server.last_seen_at).total_seconds() if server.last_seen_at else None,
        heartbeat_timeout_seconds=settings.heartbeat_timeout_seconds,
        active_alert_kinds=sorted(kinds),
    )


@router.get("/{server_id}/metrics/latest", dependencies=[Depends(viewer_access)], response_model=MetricOut)
def get_latest_metrics(server_id: int, db: Session = Depends(get_db)):
    get_server_or_404(db, server_id)
    latest = latest_metric(db, server_id)
    if latest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This server has not reported yet")
    return latest


@router.get("/{server_id}/metrics", dependencies=[Depends(viewer_access)], response_model=HistoryOut)
def get_metric_history(
    server_id: int,
    range: HistoryRange = Query("1h", description="Time window: 1h, 6h, 24h or 7d"),
    db: Session = Depends(get_db),
):
    get_server_or_404(db, server_id)
    return metric_history(db, server_id, range, utcnow())
