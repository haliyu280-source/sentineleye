from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .timeutil import UTCDateTime, utcnow

# Alert kinds and states are plain strings so the schema stays portable between SQLite and PostgreSQL.
THRESHOLD_KINDS = ("cpu_high", "memory_high", "disk_high")
OFFLINE_KIND = "server_offline"
ALERT_KINDS = (*THRESHOLD_KINDS, OFFLINE_KIND)
ALERT_STATUSES = ("open", "acknowledged", "resolved")


class Server(Base):
    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(String(500))
    environment: Mapped[str | None] = mapped_column(String(50))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Per-server overrides; NULL means "use the global default"
    cpu_threshold: Mapped[float | None] = mapped_column(Float)
    memory_threshold: Mapped[float | None] = mapped_column(Float)
    disk_threshold: Mapped[float | None] = mapped_column(Float)

    # Reported by the agent
    hostname: Mapped[str | None] = mapped_column(String(255))
    os_name: Mapped[str | None] = mapped_column(String(100))
    os_version: Mapped[str | None] = mapped_column(String(100))
    kernel: Mapped[str | None] = mapped_column(String(100))
    agent_version: Mapped[str | None] = mapped_column(String(32))
    uptime_seconds: Mapped[float | None] = mapped_column(Float)
    failed_deliveries: Mapped[int] = mapped_column(Integer, default=0)
    last_agent_error: Mapped[str | None] = mapped_column(String(500))

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    first_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    tokens: Mapped[list["AgentToken"]] = relationship(
        back_populates="server", cascade="all, delete-orphan", passive_deletes=True
    )
    metrics: Mapped[list["Metric"]] = relationship(
        back_populates="server", cascade="all, delete-orphan", passive_deletes=True
    )
    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="server", cascade="all, delete-orphan", passive_deletes=True
    )


class AgentToken(Base):
    __tablename__ = "agent_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    token_id: Mapped[str] = mapped_column(String(32), unique=True)  # public part, safe to show
    secret_hash: Mapped[str] = mapped_column(String(64))  # SHA-256 of the secret part only
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    server: Mapped[Server] = relationship(back_populates="tokens")


class Metric(Base):
    __tablename__ = "metrics"
    __table_args__ = (Index("ix_metrics_server_time", "server_id", "collected_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"))
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    cpu_percent: Mapped[float] = mapped_column(Float)
    memory_total_bytes: Mapped[int] = mapped_column(BigInteger)
    memory_used_bytes: Mapped[int] = mapped_column(BigInteger)
    memory_available_bytes: Mapped[int] = mapped_column(BigInteger)
    memory_percent: Mapped[float] = mapped_column(Float)
    disk_total_bytes: Mapped[int] = mapped_column(BigInteger)
    disk_used_bytes: Mapped[int] = mapped_column(BigInteger)
    disk_available_bytes: Mapped[int] = mapped_column(BigInteger)
    disk_percent: Mapped[float] = mapped_column(Float)
    uptime_seconds: Mapped[float] = mapped_column(Float)

    server: Mapped[Server] = relationship(back_populates="metrics")


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        # At most one active (open or acknowledged) alert per server and kind
        Index(
            "uq_alerts_active",
            "server_id",
            "kind",
            unique=True,
            sqlite_where=text("status != 'resolved'"),
            postgresql_where=text("status != 'resolved'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("servers.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    severity: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(String(300))

    threshold: Mapped[float | None] = mapped_column(Float)
    trigger_value: Mapped[float | None] = mapped_column(Float)
    last_value: Mapped[float | None] = mapped_column(Float)
    peak_value: Mapped[float | None] = mapped_column(Float)

    opened_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_observed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    resolution: Mapped[str | None] = mapped_column(String(16))  # "recovered" or "manual"

    server: Mapped[Server] = relationship(back_populates="alerts")
    events: Mapped[list["AlertEvent"]] = relationship(
        back_populates="alert",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AlertEvent.at",
    )


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id", ondelete="CASCADE"), index=True)
    event: Mapped[str] = mapped_column(String(32))  # opened, acknowledged, resolved, recovered, notified, notify_failed
    actor: Mapped[str] = mapped_column(String(16))  # "system" or "admin"
    detail: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)

    alert: Mapped[Alert] = relationship(back_populates="events")
