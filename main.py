# SentinelEye. Copyright (c) 2026 Ali Khaleel Hassan. All rights reserved. See LICENSE.

from fastapi import FastAPI
from fastapi.responses import JSONResponse
import subprocess
import json

from sentineleye import __version__
from sentineleye.web import lifespan, mount_dashboard, setup

app = FastAPI(
    title="SentinelEye",
    description="SentinelEye: A sharper eye on your infrastructure. Monitors system health, detects resource usage issues and provides clear infrastructure visibility.",
    version=__version__,
    contact={"name": "Ali K. Hassan"},
    lifespan=lifespan,
)
setup(app)


@app.get("/api/health")
def get_health():
    try:
        result = subprocess.run(
            ["bash", "sentinel.sh"],
            capture_output=True,
            text=True,
            env={**__import__("os").environ, "OUTPUT_FORMAT": "json"}
        )

        # sentinel.sh exits 1 when a check reports a warning; its JSON is still valid
        if result.returncode not in (0, 1):
            raise subprocess.CalledProcessError(result.returncode, result.args)

        health_data = json.loads(result.stdout)

        return health_data

    except subprocess.CalledProcessError:
        return JSONResponse(
            status_code=500,
            content={"error": "SentinelEye script failed"}
        )

    except json.JSONDecodeError:
        return JSONResponse(
            status_code=500,
            content={"error": "Invalid JSON returned by SentinelEye"}
        )


# Registered last so the dashboard's catch-all route never shadows an API route
mount_dashboard(app)
