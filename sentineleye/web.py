"""Wires the platform into the FastAPI app defined in main.py."""

import asyncio
import contextlib
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .api import agent, alerts, overview, servers
from .config import get_settings
from .db import SessionLocal, init_db
from .services.maintenance import background_loop

log = logging.getLogger("sentineleye")


class BodySizeLimit:
    """Rejects request bodies over a fixed size, whether or not Content-Length is sent."""

    class _TooLarge(Exception):
        pass

    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return

        length = dict(scope["headers"]).get(b"content-length")
        if length is not None and length.isdigit() and int(length) > self.max_bytes:
            await self._reject(send)
            return

        received = 0
        started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise self._TooLarge
            return message

        async def tracking_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except self._TooLarge:
            if not started:
                await self._reject(send)

    async def _reject(self, send):
        body = json.dumps({"detail": f"Request body exceeds {self.max_bytes} bytes"}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db()
    if not settings.admin_token:
        log.warning("SENTINELEYE_ADMIN_TOKEN is not set; the management API and fleet dashboard are disabled")

    task = asyncio.create_task(background_loop(settings)) if settings.run_background_jobs else None
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def setup(app: FastAPI) -> None:
    settings = get_settings()
    app.add_middleware(BodySizeLimit, max_bytes=settings.max_request_bytes)
    if settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.allowed_origins,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )

    for module in (servers, agent, overview, alerts):
        app.include_router(module.router)

    @app.get("/healthz", tags=["service"], include_in_schema=False)
    def healthz():
        """Liveness/readiness probe for Docker: the process is up and the database answers."""
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ok"}


def mount_dashboard(app: FastAPI) -> None:
    """Serve the built dashboard from the same origin as the API. Must be called after all routes."""
    dist = Path(get_settings().frontend_dist)
    if (dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=dist, html=True), name="dashboard")
