from datetime import timedelta

from sqlalchemy import func, select

from sentineleye import notify
from sentineleye.config import get_settings
from sentineleye.db import SessionLocal
from sentineleye.models import Metric
from sentineleye.services.maintenance import purge_old_metrics, run_once
from sentineleye.timeutil import utcnow
from test_history import _insert_series


def test_retention_removes_only_expired_metrics(client, register):
    server_id, _ = register()
    days = get_settings().metric_retention_days
    _insert_series(server_id, [10, (days + 1) * 24 * 60], cpu=10)
    with SessionLocal() as db:
        assert purge_old_metrics(db, get_settings(), utcnow()) == 1
        db.commit()
        assert db.scalar(select(func.count()).select_from(Metric)) == 1


def test_background_cycle_runs(client, register, submit):
    server_id, token = register()
    submit(server_id, token)
    run_once(get_settings(), utcnow() + timedelta(minutes=5), purge=True)
    assert client.get(
        "/api/alerts", params={"kind": "server_offline"}, headers={"Authorization": "Bearer test-admin-token"}
    ).json()[0]["status"] == "open"


def test_email_is_sent_after_commit_when_configured(client, register, submit, monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            sent.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            sent.append(("starttls",))

        def login(self, user, password):
            sent.append(("login", user))

        def send_message(self, msg):
            sent.append(("send", msg["Subject"], msg["To"]))

    class InlineThread:
        def __init__(self, target, args, daemon):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(notify.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(notify.threading, "Thread", InlineThread)
    monkeypatch.setenv("SENTINELEYE_SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SENTINELEYE_SMTP_FROM", "sentineleye@test")
    monkeypatch.setenv("SENTINELEYE_SMTP_TO", "ops@test, oncall@test")
    monkeypatch.setenv("SENTINELEYE_SMTP_USERNAME", "mailer")
    get_settings.cache_clear()
    try:
        server_id, token = register()
        submit(server_id, token, cpu=99)
        assert sent == []  # grace period: nothing opened, nothing sent
        submit(server_id, token, cpu=99)
        submit(server_id, token, cpu=10)
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()

    subjects = [entry[1] for entry in sent if entry[0] == "send"]
    assert len(subjects) == 2
    assert subjects[0].startswith("[SentinelEye] WARNING: web-01: CPU at 99.0%")
    assert subjects[1] == "[SentinelEye] RECOVERED: web-01: cpu high"
    assert ("send", subjects[0], "ops@test, oncall@test") in sent


def test_email_failure_does_not_break_ingestion(client, register, submit, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("connection refused")

    class InlineThread:
        def __init__(self, target, args, daemon):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(notify.smtplib, "SMTP", broken)
    monkeypatch.setattr(notify.threading, "Thread", InlineThread)
    monkeypatch.setenv("SENTINELEYE_SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SENTINELEYE_SMTP_FROM", "a@test")
    monkeypatch.setenv("SENTINELEYE_SMTP_TO", "b@test")
    get_settings.cache_clear()
    try:
        server_id, token = register()
        assert submit(server_id, token, cpu=99).status_code == 202
        assert submit(server_id, token, cpu=99).status_code == 202
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
