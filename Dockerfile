# syntax=docker/dockerfile:1

# ---- Dashboard build ----
FROM node:22-alpine AS dashboard
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- Central backend ----
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SENTINELEYE_DATABASE_URL=sqlite:////data/sentineleye.db \
    SENTINELEYE_FRONTEND_DIST=/app/frontend/dist

# procps provides ps/free/uptime for sentinel.sh behind GET /api/health
RUN apt-get update \
 && apt-get install -y --no-install-recommends procps \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin sentineleye \
 && install -d -o sentineleye -g sentineleye /data

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py sentinel.sh ./
COPY sentineleye/ sentineleye/
COPY --from=dashboard /build/dist frontend/dist

USER sentineleye
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import sys, urllib.request; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status != 200)"]

# Behind a TLS-terminating reverse proxy, set FORWARDED_ALLOW_IPS to the proxy's address
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
