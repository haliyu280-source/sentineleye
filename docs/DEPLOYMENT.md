# Deployment

This covers running SentinelEye on a development machine, deploying it with Docker, installing
agents, and putting HTTPS in front of it. Commands are run from the repository root unless stated
otherwise.

## Local development versus a public deployment

| | Local development | Public deployment |
|---|---|---|
| Dashboard address | `http://localhost:5173` (Vite dev server) | Your domain, e.g. `https://monitor.example.com` |
| API address | `http://127.0.0.1:8000` | Same domain as the dashboard |
| Reachable from | This machine only | The internet, through a reverse proxy |
| TLS | None | Required, terminated by the reverse proxy |
| Agents | On this machine or local VMs/containers | Real servers anywhere that can reach the domain |

`http://localhost:5173` exists only on the computer running the development server. It is not a
demo link and cannot be opened by anyone else. A publicly reachable instance needs a host with a
public address, the Docker deployment below and a reverse proxy with a certificate.

## Prerequisites

- **Development:** Python 3.11 or newer, Node.js 20 or newer, npm, Bash.
- **Docker deployment:** Docker Engine with the Compose plugin.
- **Monitored servers:** Linux with systemd and Python 3.10 or newer. Tested on Ubuntu 24.04.

## Configuration

All backend settings are environment variables, read from the process environment or from a
`.env` file in the working directory. Start from the template:

```bash
cp .env.example .env
chmod 600 .env
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put the generated value in `SENTINELEYE_ADMIN_TOKEN`. `.env` is ignored by git and excluded from
the Docker build.

| Variable | Default | Purpose |
|---|---|---|
| `SENTINELEYE_ADMIN_TOKEN` | unset | Admin token. Unset means the management API is disabled (503). |
| `SENTINELEYE_PUBLIC_DASHBOARD` | `false` | Allow read-only access without a token |
| `SENTINELEYE_DATABASE_URL` | `sqlite:///./data/sentineleye.db` | Database location. PostgreSQL: `postgresql://user:password@host:5432/dbname` |
| `SENTINELEYE_HEARTBEAT_TIMEOUT_SECONDS` | `90` | Silence before a server is offline |
| `SENTINELEYE_BACKGROUND_INTERVAL_SECONDS` | `15` | How often offline checks run |
| `SENTINELEYE_RUN_BACKGROUND_JOBS` | `true` | Turn the background job off (tests use this) |
| `SENTINELEYE_ALERT_CONSECUTIVE_BREACHES` | `2` | Breaching samples needed to open an incident |
| `SENTINELEYE_DEFAULT_CPU_THRESHOLD` | `80` | Default CPU limit, % |
| `SENTINELEYE_DEFAULT_MEMORY_THRESHOLD` | `85` | Default memory limit, % |
| `SENTINELEYE_DEFAULT_DISK_THRESHOLD` | `80` | Default disk limit, % |
| `SENTINELEYE_METRIC_RETENTION_DAYS` | `30` | Metrics older than this are deleted hourly |
| `SENTINELEYE_MAX_CLOCK_SKEW_SECONDS` | `300` | Accepted difference between agent and server clocks |
| `SENTINELEYE_AGENT_RATE_LIMIT_PER_MINUTE` | `30` | Reports per agent token per minute |
| `SENTINELEYE_ADMIN_AUTH_FAILURES_PER_MINUTE` | `10` | Failed authentications per client address per minute |
| `SENTINELEYE_MAX_REQUEST_BYTES` | `65536` | Maximum request body |
| `SENTINELEYE_TOKEN_TTL_DAYS` | unset | Expiry for newly issued agent tokens |
| `SENTINELEYE_SMTP_HOST`, `_PORT`, `_USERNAME`, `_PASSWORD`, `_FROM`, `_TO`, `_STARTTLS` | unset / `587` / … / `true` | Optional e-mail notifications. `_TO` is a comma-separated list. |
| `SENTINELEYE_FRONTEND_DIST` | `frontend/dist` | Built dashboard served by the backend |
| `SENTINELEYE_CORS_ORIGINS` | empty | Comma-separated origins, only if the dashboard is served from another origin |

## Running locally

**Backend:**

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m uvicorn main:app --reload
```

The API listens on `http://127.0.0.1:8000`; interactive docs are at `http://127.0.0.1:8000/docs`.
Run it from the repository root: `GET /api/health` calls `sentinel.sh` by relative path, and the
default SQLite file is created in `./data/`. (`python -m fastapi dev main.py` also works, but only
if `fastapi[standard]` is installed, which `requirements.txt` does not include.)

**Dashboard**, in a second terminal:

```bash
npm --prefix frontend install
npm --prefix frontend run dev
```

Open `http://localhost:5173`. The dev server proxies `/api` to `http://127.0.0.1:8000`; to use a
backend elsewhere:

```bash
SENTINELEYE_API_URL=http://127.0.0.1:8001 npm --prefix frontend run dev
```

If `npm run build` has been run, the backend also serves the built dashboard itself at
`http://127.0.0.1:8000`.

**The standalone script:**

```bash
bash sentinel.sh
OUTPUT_FORMAT=json bash sentinel.sh
DISK_THRESHOLD=70 CPU_THRESHOLD=90 bash sentinel.sh
```

## Docker deployment

```bash
cp .env.example .env            # set SENTINELEYE_ADMIN_TOKEN
docker compose up -d --build
docker compose ps               # wait for "healthy"
curl http://127.0.0.1:8000/healthz
```

What `Dockerfile` and `compose.yaml` set up:

| | |
|---|---|
| Build | Stage 1 (`node:22-alpine`) builds the dashboard; stage 2 (`python:3.12-slim`) installs `requirements.txt` and `procps`, copies `main.py`, `sentinel.sh`, `sentineleye/` and the built dashboard |
| Process | `uvicorn main:app --host 0.0.0.0 --port 8000 --proxy-headers` as user `sentineleye` (uid 10001) |
| Port | `127.0.0.1:8000` on the host; override with `SENTINELEYE_BIND` and `SENTINELEYE_PORT` |
| Data | Named volume `sentineleye-data` at `/data`; the database is `/data/sentineleye.db` |
| Health check | `GET /healthz` (process up and a database query succeeds), every 30 s |
| Restart | `unless-stopped` |
| Hardening | Read-only root filesystem, `tmpfs` at `/tmp`, all capabilities dropped, `no-new-privileges` |
| Logs | `json-file`, 3 files of 10 MB |

Compose refuses to start if `SENTINELEYE_ADMIN_TOKEN` is empty. Inside the container,
`GET /api/health` runs `sentinel.sh` against the container's own view of the system.

Useful commands:

```bash
docker compose logs -f sentineleye
docker compose restart
docker compose down             # stops; the data volume is kept
docker compose up -d --build    # after pulling new code
```

### Database persistence

All state is in the SQLite file on the `sentineleye-data` volume. It survives `restart`,
`down` and image rebuilds; `docker compose down -v` deletes it. A consistent copy while running:

```bash
docker compose exec sentineleye python -c "import sqlite3; s=sqlite3.connect('/data/sentineleye.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d)"
docker compose cp sentineleye:/data/backup.db ./sentineleye-backup.db
```

## HTTPS

The backend does not terminate TLS. Anything reachable beyond localhost must sit behind a reverse
proxy with a certificate, because agents send their token, and admins their admin token, in
request headers. Agents refuse plain HTTP to non-local hosts unless `SENTINELEYE_ALLOW_HTTP=true`.

An example with Caddy, which obtains certificates automatically. Add to `compose.yaml`:

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

add `caddy-data:` under `volumes:`, and create `Caddyfile`:

```
monitor.example.com {
    reverse_proxy sentineleye:8000
}
```

This configuration is an example and has not been tested as part of this project. The domain
must point at the host, and ports 80 and 443 must be open. Keep the `sentineleye` service bound to
`127.0.0.1`, and set `FORWARDED_ALLOW_IPS` in its environment to the proxy's address so that
client addresses (used for rate limiting) are taken from `X-Forwarded-For`. With nginx, use
`proxy_pass http://127.0.0.1:8000;` and set `X-Forwarded-For` and `X-Forwarded-Proto`.

## Render

`render.yaml` is a Render Blueprint for one free Docker web service and one free Render Postgres
database in Frankfurt. Render generates `SENTINELEYE_ADMIN_TOKEN` and injects
`SENTINELEYE_DATABASE_URL` from the database, so neither is stored in the repository. The
database accepts connections only from the workspace's services. Check the file before applying
it:

```bash
render blueprints validate ./render.yaml
```

Render's free tier has limits that affect SentinelEye ([render.com/docs/free](https://render.com/docs/free)):

- The web service sleeps after 15 minutes without inbound requests. Agents reporting every 30
  seconds keep it awake; with no agents it sleeps and takes about a minute to wake.
- Its filesystem is temporary, so the database must be Postgres, not the default SQLite file.
- Free Postgres expires 30 days after creation, holds 1 GB and has no backups.
- Render asks for a payment method on the account before applying a Blueprint, even when every
  resource in it is free.

## Production configuration checklist

- `SENTINELEYE_ADMIN_TOKEN`: long and random; `.env` at mode 600.
- HTTPS proxy in front; backend port on `127.0.0.1` only.
- `SENTINELEYE_PUBLIC_DASHBOARD`: `true` only if the fleet is meant to be visible to anyone.
- `SENTINELEYE_TOKEN_TTL_DAYS`: set if agent tokens should expire.
- `SENTINELEYE_METRIC_RETENTION_DAYS`: sized for the disk (one row per server every 30 s).
- SMTP variables, if e-mail notifications are wanted.
- Regular backups of the database volume.
- NTP on the backend and on every agent host.

## Installing an agent

1. **Register the server.** In the dashboard, sign in as admin, open *Fleet* and choose *Register
   server*. Or with the API:

   ```bash
   curl -s -X POST https://monitor.example.com/api/servers \
     -H "Authorization: Bearer $SENTINELEYE_ADMIN_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"name": "web-01", "environment": "production"}'
   ```

   Keep the server `id` and the `token`. The token is shown once.

2. **Install on the server**, from a copy of the repository's `agent/` folder:

   ```bash
   cd agent
   sudo ./install.sh --url https://monitor.example.com --server-id 3
   ```

   The script prompts for the token without echoing it, or reads it from `SENTINELEYE_TOKEN`:

   ```bash
   sudo SENTINELEYE_TOKEN='se_...' ./install.sh --url https://monitor.example.com --server-id 3
   ```

   Options: `--interval SECONDS` (default 30), `--reconfigure` (replace existing configuration),
   `--allow-http` (isolated test networks only).

   It creates the `sentineleye` user, copies the agent to `/opt/sentineleye-agent`, writes
   `/etc/sentineleye-agent/agent.env` (mode 640), sends one test sample as that user and stops if
   it is rejected, then installs and restarts `sentineleye-agent.service`.

3. **Confirm.** The server shows as *Healthy* on the dashboard within one interval.

Agent configuration (`/etc/sentineleye-agent/agent.env`):

| Variable | Default | Purpose |
|---|---|---|
| `SENTINELEYE_URL` | required | Backend base URL |
| `SENTINELEYE_SERVER_ID` | required | Server id from registration |
| `SENTINELEYE_TOKEN` | required | Agent token |
| `SENTINELEYE_INTERVAL` | `30` | Seconds between samples, 5–3600 |
| `SENTINELEYE_TIMEOUT` | `10` | Request timeout, seconds |
| `SENTINELEYE_MAX_RETRIES` | `4` | Retries per sample |
| `SENTINELEYE_DISK_PATH` | `/` | Filesystem to report |
| `SENTINELEYE_CA_BUNDLE` | unset | CA file for a private certificate authority |
| `SENTINELEYE_ALLOW_HTTP` | `false` | Allow plain HTTP to a non-local host |

Service commands:

```bash
systemctl status sentineleye-agent
sudo systemctl restart sentineleye-agent
journalctl -u sentineleye-agent -f
```

Check what the agent collects without sending anything:

```bash
cd /opt/sentineleye-agent && python3 -m sentineleye_agent --print
```

Remove it:

```bash
cd agent
sudo ./uninstall.sh            # keeps /etc/sentineleye-agent
sudo ./uninstall.sh --purge    # also removes the configuration and the service user
```

More detail: [AGENT.md](AGENT.md).

## Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| Management requests return 503 | `SENTINELEYE_ADMIN_TOKEN` not set | Set it in `.env` and restart |
| Dashboard asks for a token | Public mode is off (default) | Sign in, or set `SENTINELEYE_PUBLIC_DASHBOARD=true` |
| Dashboard: "Can't reach the SentinelEye backend" | Backend not running, or wrong proxy target | Start the backend; check `SENTINELEYE_API_URL` for the dev server |
| `python -m fastapi dev` fails with a message about `fastapi[standard]` | `fastapi-cli` not installed | Use `.venv/bin/python -m uvicorn main:app --reload` |
| `GET /api/health` returns 500 | Not started from the repository root, or `bash` missing | Start from the root; in Docker this is handled |
| `docker compose up` exits: "Set SENTINELEYE_ADMIN_TOKEN in .env" | Missing token | Fill in `.env` |
| Compose: port already in use | Something already listens on 8000 | `SENTINELEYE_PORT=8080 docker compose up -d` |
| Agent log: `HTTP 401` | Token wrong, revoked, reissued or expired | Reissue and run `install.sh --reconfigure` |
| Agent log: `HTTP 403 ... server_id` | `SENTINELEYE_SERVER_ID` does not match the token | Correct the id |
| Agent log: `HTTP 422 ... too old` or `in the future` | Clock off by more than 5 minutes | `sudo timedatectl set-ntp true` |
| Agent log: `Refusing to send the agent token over plain HTTP` | `http://` URL to a remote host | Use `https://` |
| Agent log: `Cannot reach backend` | DNS, firewall or backend down | `curl -v https://monitor.example.com/healthz` from the agent host |
| Server stays *Unknown* | The agent has never delivered | Check the agent log and run `--once` by hand (see [AGENT.md](AGENT.md)) |
