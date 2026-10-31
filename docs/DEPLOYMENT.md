# Deployment guide

This covers running the central backend and dashboard with Docker Compose, putting HTTPS in front
of it, and day-to-day operation. Agents are installed separately; see [AGENT.md](AGENT.md).

## Requirements

- A Linux host with Docker Engine and the Compose plugin.
- A DNS name for the host if agents on other machines will report to it (e.g.
  `monitor.example.com`).

## 1. Configure

```bash
git clone <your copy of this repository> sentineleye && cd sentineleye
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # paste into SENTINELEYE_ADMIN_TOKEN
chmod 600 .env
```

`.env` is read at runtime and is excluded from the image by `.dockerignore`. Compose refuses to
start if `SENTINELEYE_ADMIN_TOKEN` is empty.

## 2. Start

```bash
docker compose up -d --build
docker compose ps        # STATUS should become "healthy"
curl http://127.0.0.1:8000/healthz
```

What the Compose file sets up:

| | |
|---|---|
| Image | Node stage builds the dashboard; `python:3.12-slim` runs the backend |
| Port | `127.0.0.1:8000`; change with `SENTINELEYE_BIND` / `SENTINELEYE_PORT` |
| Data | Named volume `sentineleye-data` mounted at `/data` (SQLite database) |
| User | Non-root `sentineleye` (uid 10001), read-only root filesystem, all capabilities dropped |
| Health | `GET /healthz` every 30 s (checks the process and a database query) |
| Restart | `unless-stopped` |
| Logs | `json-file`, 3 × 10 MB |

Open http://127.0.0.1:8000 and sign in with the admin token.

## 3. HTTPS (required for remote agents)

The backend speaks plain HTTP and expects a reverse proxy to terminate TLS. Agents refuse to send
their token over plain HTTP to anything but localhost, and the dashboard's admin token must not
cross a network unencrypted either.

A minimal setup with [Caddy](https://caddyserver.com/), which obtains and renews Let's Encrypt
certificates itself. Add to `compose.yaml`:

```yaml
  caddy:
    image: caddy:2
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data
    depends_on:
      - sentineleye
```

and `caddy-data:` under `volumes:`. Then create `Caddyfile`:

```
monitor.example.com {
    reverse_proxy sentineleye:8000
}
```

Keep the `sentineleye` port bound to `127.0.0.1` so it is only reachable through the proxy, and
set `FORWARDED_ALLOW_IPS` on the `sentineleye` service to the proxy's address on the Compose
network (or `*` if nothing else can reach the container) so client addresses in logs and rate
limits are the real ones.

nginx works the same way: `proxy_pass http://127.0.0.1:8000;` with `proxy_set_header
X-Forwarded-For $proxy_add_x_forwarded_for;` and `X-Forwarded-Proto $scheme`.

Agents then use `SENTINELEYE_URL=https://monitor.example.com`.

## 4. Register servers and install agents

Follow [AGENT.md](AGENT.md). In short: *Fleet → Register server*, copy the id and token, run
`sudo ./install.sh --url https://monitor.example.com --server-id <id>` on the server.

## Operations

**Logs**: `docker compose logs -f sentineleye`. Alerts are logged at WARNING with the server name;
tokens are never logged.

**Backups**: the whole state is one SQLite database in the volume. A consistent copy while
running:

```bash
docker compose exec sentineleye python -c \
  "import sqlite3; s=sqlite3.connect('/data/sentineleye.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d)"
docker compose cp sentineleye:/data/backup.db ./sentineleye-$(date +%F).db
```

**Retention**: metrics older than `SENTINELEYE_METRIC_RETENTION_DAYS` (default 30) are deleted
every hour. At a 30-second interval that is about 86,000 rows per server per month.

**E-mail**: set the `SENTINELEYE_SMTP_*` variables and restart. Messages go out when an incident
opens and when it recovers. Delivery failures are logged and never affect monitoring.

**Upgrades**:

```bash
git pull
docker compose up -d --build
```

Tables are created on start-up if missing. There are no schema migrations yet, so read the
release notes before upgrading across versions that change the data model.

**PostgreSQL**: set `SENTINELEYE_DATABASE_URL=postgresql+psycopg://user:pass@host/sentineleye` and
add a PostgreSQL driver (`psycopg[binary]`) to `requirements.txt`. The models are written for both
databases, but only SQLite has been tested.

## Running without Docker

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
npm --prefix frontend ci && npm --prefix frontend run build
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --proxy-headers
```

Run it under systemd or another supervisor, from the repository root (the backend calls
`sentinel.sh` by relative path), behind the same kind of HTTPS proxy.
