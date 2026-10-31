from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_serializer, model_validator

from .timeutil import as_utc

Percent = Field(ge=0, le=100)
Bytes = Field(ge=0, le=2**62)
ServerStatus = Literal["healthy", "warning", "offline", "unknown", "disabled"]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("*", when_used="json", check_fields=False)
    def _utc(self, value):
        # Every timestamp leaves the API as ISO 8601 UTC with an explicit offset
        if isinstance(value, datetime):
            return as_utc(value).isoformat().replace("+00:00", "Z")
        return value


# ---------- Agent ingestion ----------


class AgentOS(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    version: str = Field(default="", max_length=100)
    kernel: str = Field(default="", max_length=100)


class AgentMemory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_bytes: int = Field(gt=0, le=2**62)
    used_bytes: int = Bytes
    available_bytes: int = Bytes
    percent: float = Percent

    @model_validator(mode="after")
    def _consistent(self):
        if self.used_bytes > self.total_bytes or self.available_bytes > self.total_bytes:
            raise ValueError("memory used/available cannot exceed total")
        return self


class AgentDisk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mount: str = Field(default="/", max_length=255)
    total_bytes: int = Field(gt=0, le=2**62)
    used_bytes: int = Bytes
    available_bytes: int = Bytes
    percent: float = Percent

    @model_validator(mode="after")
    def _consistent(self):
        if self.used_bytes > self.total_bytes or self.available_bytes > self.total_bytes:
            raise ValueError("disk used/available cannot exceed total")
        return self


class AgentDelivery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    failed_attempts: int = Field(default=0, ge=0, le=1_000_000)
    last_error: str | None = Field(default=None, max_length=500)


class MetricSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_id: int = Field(gt=0)
    collected_at: AwareDatetime
    hostname: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9._-]+$")
    agent_version: str = Field(min_length=1, max_length=32)
    os: AgentOS
    uptime_seconds: float = Field(ge=0, le=10 * 365 * 86400)
    cpu_percent: float = Percent
    memory: AgentMemory
    disk: AgentDisk
    delivery: AgentDelivery = AgentDelivery()


class SubmissionAccepted(BaseModel):
    accepted: bool = True
    server_status: ServerStatus


# ---------- Servers ----------


class Thresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cpu: float | None = Field(default=None, gt=0, le=100)
    memory: float | None = Field(default=None, gt=0, le=100)
    disk: float | None = Field(default=None, gt=0, le=100)


class ServerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")
    description: str | None = Field(default=None, max_length=500)
    environment: str | None = Field(default=None, max_length=50)
    thresholds: Thresholds = Thresholds()


class ServerUpdate(BaseModel):
    """Fields left out are unchanged. Send a threshold as null to fall back to the global default."""

    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")
    description: str | None = Field(default=None, max_length=500)
    environment: str | None = Field(default=None, max_length=50)
    enabled: bool | None = None
    thresholds: Thresholds | None = None


class MetricOut(ApiModel):
    collected_at: datetime
    received_at: datetime
    cpu_percent: float
    memory_total_bytes: int
    memory_used_bytes: int
    memory_available_bytes: int
    memory_percent: float
    disk_total_bytes: int
    disk_used_bytes: int
    disk_available_bytes: int
    disk_percent: float
    uptime_seconds: float


class EffectiveThresholds(BaseModel):
    cpu: float
    memory: float
    disk: float


class ServerOut(ApiModel):
    id: int
    name: str
    description: str | None
    environment: str | None
    enabled: bool
    status: ServerStatus
    hostname: str | None
    os_name: str | None
    os_version: str | None
    kernel: str | None
    agent_version: str | None
    uptime_seconds: float | None
    failed_deliveries: int
    last_agent_error: str | None
    thresholds: EffectiveThresholds
    threshold_overrides: Thresholds
    created_at: datetime
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    latest: MetricOut | None
    active_alerts: int


class TokenOut(ApiModel):
    token_id: str
    created_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    last_used_at: datetime | None


class IssuedTokenOut(BaseModel):
    server_id: int
    token_id: str
    token: str = Field(description="Full agent token. Shown once; store it on the agent host.")


class ServerCreated(BaseModel):
    server: ServerOut
    agent_token: IssuedTokenOut


class ServerStatusOut(ApiModel):
    server_id: int
    status: ServerStatus
    last_seen_at: datetime | None
    seconds_since_last_seen: float | None
    heartbeat_timeout_seconds: int
    active_alert_kinds: list[str]


# ---------- History & overview ----------

HistoryRange = Literal["1h", "6h", "24h", "7d"]


class HistoryPoint(ApiModel):
    t: datetime
    cpu: float
    memory: float
    disk: float
    samples: int


class HistoryOut(ApiModel):
    server_id: int
    range: HistoryRange
    start: datetime
    end: datetime
    raw_samples: int
    bucket_seconds: int | None
    points: list[HistoryPoint]


class Averages(BaseModel):
    cpu: float | None
    memory: float | None
    disk: float | None
    reporting_servers: int


class OverviewOut(ApiModel):
    generated_at: datetime
    servers: dict[str, int]
    averages: Averages
    alerts: dict[str, int]
    heartbeat_timeout_seconds: int


# ---------- Alerts ----------


class AlertEventOut(ApiModel):
    id: int
    alert_id: int
    event: str
    actor: str
    detail: str | None
    at: datetime


class AlertOut(ApiModel):
    id: int
    server_id: int
    server_name: str
    kind: str
    status: str
    severity: str
    message: str
    threshold: float | None
    trigger_value: float | None
    last_value: float | None
    peak_value: float | None
    opened_at: datetime
    last_observed_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    resolution: str | None


class AlertDetail(AlertOut):
    events: list[AlertEventOut]


class AlertActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=500)


class ActivityOut(AlertEventOut):
    server_id: int
    server_name: str
    kind: str
