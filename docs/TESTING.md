# Testing

Two kinds of evidence are kept separate on purpose:

- **Automated tests** use **controlled values**: recorded `/proc` files and hand-built payloads.
  They run on any machine and prove the logic.
- **Live verification** ran the real system on Ubuntu 24.04 hosts with **real metrics**. It shows
  the pieces working together on the target platform.

## Running the tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

`pyproject.toml` points pytest at `tests/` and `agent/tests/` and puts the repository root and
`agent/` on the import path. Each backend test gets a fresh SQLite database in a temporary
directory, a fixed admin token, background jobs switched off and public mode off, so a
developer's local `.env` cannot change the results.

Dashboard checks:

```bash
npm --prefix frontend run lint
npm --prefix frontend run build
```

Script syntax:

```bash
bash -n sentinel.sh agent/install.sh agent/uninstall.sh
```

### Latest results

Run on macOS with Python 3.14:

| Check | Result |
|---|---|
| `python -m pytest` | **92 passed** |
| Same suite in a freshly created virtual environment from `requirements-dev.txt` | 92 passed |
| `npm run lint` | no findings |
| `npm run build` | succeeded |
| `bash -n` on the three scripts | no errors |

## Test organisation

| File | Tests | Area |
|---|---:|---|
| `tests/test_app.py` | 7 | Start-up, original endpoint, OpenAPI, admin authentication |
| `tests/test_servers.py` | 9 | Registration, management, tokens |
| `tests/test_agent_ingest.py` | 7 | Metric submission and its safeguards |
| `tests/test_alerts.py` | 10 | Alert engine and offline detection |
| `tests/test_history.py` | 4 | History ranges, downsampling, overview |
| `tests/test_maintenance.py` | 4 | Retention, background cycle, e-mail |
| `tests/test_public_mode.py` | 7 | Public read-only access |
| `tests/test_integration.py` | 2 | Real agent code against the real backend |
| `agent/tests/test_collector.py` | 11 | `/proc` parsing and calculations |
| `agent/tests/test_config.py` | 15 | Agent configuration |
| `agent/tests/test_client_and_loop.py` | 16 | HTTP client, error handling, retries |
| **Total** | **92** | |

## What is covered

### Backend and authentication

- The app starts and `/healthz` reaches the database.
- `GET /api/health` runs the real `sentinel.sh` and still returns its original fields; it needs no
  credentials.
- The OpenAPI document lists the platform endpoints and `/docs` loads.
- Management endpoints reject missing, wrong and non-Bearer credentials; return 503 when no admin
  token is configured; and rate-limit repeated failures (the 11th failure in a minute gets 429).
- Registration returns a correctly formatted token once and stores only its hash; the secret does
  not appear in list, detail or token responses.
- Duplicate names (409), invalid names, out-of-range limits and unknown fields (422).
- List, get, update, per-server limits and resetting a limit to the default with `null`.
- Disabled servers are reported as *disabled* and their agents are refused.
- Deleting a server removes its metrics and tokens, and its token stops working.
- Revoke, additional token and reissue (which revokes every older token); expired tokens are
  refused; malformed `Authorization` headers are refused.

### Metric ingestion

- An accepted sample is stored and updates hostname, OS, last seen time and the latest metrics.
- A token cannot submit for another server (403) and nothing is stored.
- Rejected payloads: CPU above 100 or below 0, invalid hostname, unknown fields, a timestamp
  without a time zone, memory used above total, a missing section.
- Stale (10 minutes old) and future (10 minutes ahead) samples get 422; a replayed or older sample
  gets 409.
- A body over 64 KB gets 413.
- With the limit lowered to 3 per minute, the fourth report gets 429.
- Delivery failures reported by the agent are stored and cleared by the next clean report.

### Alerts, offline detection and recovery

- One breach shows *warning* without opening an incident.
- Two consecutive breaches open exactly one incident; further breaches update it (same id, peak
  and last value updated).
- A sample below the limit resolves it as *recovered* with an event saying so; a later breach
  opens a new incident.
- Memory and disk incidents; per-server limits apply only to their server.
- Acknowledge, then resolve, with notes recorded in the timeline; acknowledging twice or resolving
  a resolved incident gets 409; an acknowledged incident still absorbs further breaches.
- Filters by status, server and kind.
- A server silent past the timeout is *offline*; the heartbeat check opens one *server
  unavailable* incident and does not duplicate it; the next report recovers it.
- A server that never reported stays *unknown* and never gets an offline incident.
- The activity feed lists events newest first.

### History and retention

- 1h, 6h, 24h and 7d windows include exactly the samples inside them; an invalid range gets 422.
- 700 samples over a day are averaged into 240-second buckets, no more than 360 points, and every
  sample is accounted for.
- `metrics/latest` returns 404 before the first report.
- The overview counts servers by status and averages only reporting servers.
- Retention deletes only rows older than the retention period.
- One background cycle opens an offline incident.

### Notifications

With a simulated SMTP class: nothing is sent during the grace period, one message is sent when an
incident opens and one when it recovers, to every recipient; an SMTP failure does not affect
ingestion. No real mail server was used.

### Public read-only mode

- Private by default: every read endpoint returns 401 without a token.
- Public mode: all nine read endpoints return 200 without a token.
- All eight state-changing and token endpoints still return 401, and nothing changes.
- Agent error text is hidden from anonymous responses but visible to the admin.
- A wrong token is still rejected; the admin can still manage.

### Agent

- CPU from two `/proc/stat` samples, including the zero-progress error case.
- Memory from `MemAvailable`, and an error when it is missing.
- Disk figures match the `df` formula; uptime; `os-release` with and without the file; hostname
  cleaning.
- `validate_sample` rejects impossible values; non-Linux systems are detected.
- Configuration: valid values and defaults; each required variable missing or malformed;
  interval bounds; missing CA file; plain HTTP refused for remote hosts and allowed for localhost
  or with the override; file parsing, quoting and precedence (environment wins); the token never
  appears in the configuration's text representation.
- Client: the request carries the token and payload; 401, 403 and 422 are not retried; 429, 503,
  connection errors and timeouts are; validation messages are readable; non-JSON and unconfirmed
  responses are errors.
- Loop: two failures then success sends the failure count with the successful sample and resets
  it; giving up after the retry limit keeps the count for the next cycle; authentication failures
  are not retried; a 409 is not counted as a failure; backoff never exceeds half the interval.

### Integration

`tests/test_integration.py` runs the real agent (configuration loader, `/proc` collector, HTTP
client and loop) against the real FastAPI app through an in-process transport. The test writes
the `/proc` files, so the values are controlled:

1. Register a server and receive its token.
2. Configure the agent with it and report a normal sample.
3. Check the database rows and the server as seen through the API.
4. Report 92 % and 95 % CPU: one incident opens.
5. Report 30 %: it recovers.
6. Evaluate heartbeats five minutes later: a *server unavailable* incident opens.
7. Report again: it recovers.
8. The 1h history shows all five samples.

A second test runs two agents side by side and confirms that one cannot report as the other.

## Live verification

Performed on 31 October 2026 against the development backend, with agents installed by
`install.sh` in two `ubuntu:24.04` containers running systemd (Ubuntu 24.04.5 LTS, Docker Desktop
on macOS). These used real metrics, real load and real outages.

| Check | Observed |
|---|---|
| `sentinel.sh` on Ubuntu 24.04.5: `bash -n`, text, JSON, `DISK_THRESHOLD=1`, `DISK_THRESHOLD=abc`, `CPU_THRESHOLD=150` | Same behaviour as on macOS, exit code 1 on warnings |
| `sentinel.sh` on macOS, before and after its JSON gained per-check fields | Original fields unchanged |
| `install.sh` | Service user created, configuration `640 root:sentineleye`, test sample accepted, service active |
| Agent process | Ran as `sentineleye`, about 23 MB resident memory |
| `systemd-analyze security sentineleye-agent` | Exposure 4.0, "OK" |
| Agent figures vs. the host's tools | Memory total and disk used and total identical to `free -b` and `df -B1` |
| Token in the agent journal and container logs | Not present |
| Busy loops on all 8 CPUs for 75 s | CPU at 100 %; one `cpu_high` incident per server after two reports |
| Load stopped | Incidents resolved as *recovered*, peak 100 % recorded |
| `systemctl stop sentineleye-agent` | Server *offline*; critical *server unavailable* incident 101 s after the last report |
| Acknowledge from the dashboard | Incident *acknowledged*, event recorded |
| `systemctl start sentineleye-agent` | Incident recovered 4 s later |
| Token revoked | Agent logged `HTTP 401`, no retry storm |
| Token reissued, `install.sh --reconfigure` | Agent reporting again |

The reissue step found a bug that is now fixed: the installer used `systemctl enable --now`, which
does not restart a running service, so the agent kept its old token. It now restarts the service.

Both containers share Docker Desktop's Linux VM, so they reported the same machine's CPU and
memory; that is why the load test opened an incident on both. Separate servers or VMs report their
own figures.

### Docker validation

| Check | Observed |
|---|---|
| `docker compose build` | Image built (266 MB) |
| Container health | *healthy* |
| Runtime user and filesystem | `sentineleye` (uid 10001); writing to `/app` fails (read-only) |
| `/`, `/docs`, `/api/health` | 200; `/api/health` ran `sentinel.sh` inside the container |
| Management API without token | 401 |
| Agent on Ubuntu reporting to the containerised backend | Sample accepted |
| `docker compose restart` and `down` followed by `up` | Data kept |
| Tokens in container logs | Not present |

### Dashboard checks

In a browser: healthy, warning and offline states; sign-in with a wrong and a valid token;
acknowledging an incident; the public read-only view showing data with no management controls;
layouts at 1280, 375 and 320 px wide without horizontal scrolling; no console errors on a fresh
load.

## Repeating the live check

```bash
cat > Dockerfile.ubuntu <<'EOF'
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends systemd systemd-sysv python3 procps ca-certificates
CMD ["/sbin/init"]
EOF
docker build -t sentineleye-test/ubuntu-systemd -f Dockerfile.ubuntu .
docker run -d --name node1 --privileged --cgroupns=host -v /sys/fs/cgroup:/sys/fs/cgroup:rw sentineleye-test/ubuntu-systemd
docker cp agent node1:/root/agent
docker exec -it node1 bash -c "cd /root/agent && ./install.sh --url http://host.docker.internal:8000 --server-id 1"
```

Generate load for about 75 seconds and watch an incident open and recover:

```bash
docker exec -d node1 bash -c 'for i in $(seq $(nproc)); do (timeout 75 sh -c "while :; do :; done" &); done'
```

Simulate an outage; the server goes offline after 90 seconds and recovers on the next report:

```bash
docker exec node1 systemctl stop sentineleye-agent
docker exec node1 systemctl start sentineleye-agent
```

## Not tested

- PostgreSQL.
- Linux distributions other than Ubuntu 24.04.
- Delivery through a real SMTP server.
- The Caddy example in [DEPLOYMENT.md](DEPLOYMENT.md), or any real TLS deployment.
- Load beyond two agents.
