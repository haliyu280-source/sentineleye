# Testing

There are two kinds of evidence here, kept separate on purpose:

- **Automated tests** run on any machine and use **controlled values**: fixed `/proc` files and
  hand-built payloads. They prove the logic.
- **Live verification** ran the real system on Ubuntu 24.04 hosts with **real metrics**. It proves
  the pieces work together on the target platform.

## Automated tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Last run: **92 passed** (Python 3.14, macOS). Frontend: `npm --prefix frontend run lint` and
`npm --prefix frontend run build`, both clean.

### Backend (`tests/`, 48 tests)

| File | Covers |
|---|---|
| `test_app.py` | start-up and database probe; original `/api/health` contract (runs the real `sentinel.sh`); OpenAPI docs; admin auth required, disabled without a configured token, failures rate-limited |
| `test_servers.py` | registration returns a valid token once and stores only its hash; name conflicts; input validation; list/get/update; per-server limits and reset to default; disable; delete with cascade; revoke, additional token, reissue; expired tokens; malformed auth headers |
| `test_agent_ingest.py` | metric storage and server updates; agent cannot report for another server; invalid payloads (ranges, used > total, unknown fields, naive timestamps); stale, future and replayed samples; 64 KB body limit; per-agent rate limit; delivery-failure reporting |
| `test_alerts.py` | grace period (one breach shows *warning*, no alert); alert after consecutive breaches; duplicate prevention while breaching; recovery and its event; memory and disk alerts; per-server limits; acknowledge then resolve with notes; invalid transitions (409); filters; offline detection and recovery; never-reported servers stay *unknown*; activity feed |
| `test_history.py` | 1h/6h/24h/7d windows; downsampling of long ranges; latest sample; overview counts and averages |
| `test_public_mode.py` | private by default; public mode allows every read without a token; every change, and all token endpoints, still refused; agent error text hidden from anonymous viewers; wrong tokens still rejected; admin can still manage |
| `test_maintenance.py` | retention deletes only expired rows; background cycle opens offline alerts; e-mail sent only after commit and only when configured; SMTP failure does not affect ingestion |

### Agent (`agent/tests/`, 42 tests)

| File | Covers |
|---|---|
| `test_collector.py` | `/proc/stat` CPU maths over two samples; `/proc/meminfo` with `MemAvailable`; `statvfs` disk figures matching `df`; uptime; `os-release`; hostname cleaning; validation of impossible values; non-Linux detection |
| `test_config.py` | valid and default settings; each required variable; ranges; plain-HTTP refusal and its overrides; config file parsing and precedence; token never in `repr` |
| `test_client_and_loop.py` | request carries auth and payload; error classification (401/403/422 not retried, 429/5xx/network retried); unreadable and unconfirmed responses; retry with growing backoff, failure count reported on success; giving up after max retries; no retry on auth failure; 409 not counted as a failure; backoff cap |

### End to end (`tests/test_integration.py`, 2 tests)

The real agent (configuration loader, `/proc` collector, HTTP client, retry loop) reports to the
real FastAPI app through an in-process transport. `/proc` files are written by the test, so the
values are controlled. Flow: register → configure agent → report → database rows → API view →
two breaching reports open a CPU alert → a normal report recovers it → heartbeat timeout opens an
offline alert → the next report recovers it → history shows all five samples. A second test runs
two agents side by side and checks that one cannot report as the other.

## Live verification

Performed on 31 October 2026 against the development backend, with agents installed in two
`ubuntu:24.04` containers running systemd (Ubuntu 24.04.5 LTS, Docker Desktop on macOS).

| Check | Result |
|---|---|
| `sentinel.sh` on Ubuntu 24.04.5: `bash -n`, text mode, JSON mode, `DISK_THRESHOLD=1`, `=abc`, `CPU_THRESHOLD=150` | same behaviour as on macOS |
| `sentinel.sh` on macOS: same checks, before and after the change to its JSON output | existing fields identical; new per-check fields correct |
| `install.sh` | created the service user, wrote config (`640 root:sentineleye`), test sample accepted, service active |
| Agent process | runs as `sentineleye`, about 23 MB RSS; `systemd-analyze security` exposure 4.0 |
| Real metrics vs. the host's own tools | memory total and disk used/total identical to `free -b` and `df -B1` |
| Token in journal or container logs | not present |
| Real CPU load (busy loops on all 8 CPUs) | CPU 100 %, one `cpu_high` incident per server after two reports |
| Load removed | incidents resolved as *recovered*, peak 100 % recorded |
| `systemctl stop sentineleye-agent` | server *offline*; critical *server unavailable* incident 101 s after the last report |
| Acknowledge from the dashboard | status *acknowledged*, event recorded |
| `systemctl start sentineleye-agent` | incident recovered 4 s later |
| Revoke token | agent logs `HTTP 401`, no retry storm |
| Reissue + `install.sh --reconfigure` | agent reporting again (this check found and fixed a bug: the installer now restarts a running service) |
| Docker image | builds; container *healthy*; non-root, read-only; dashboard, `/docs`, `/api/health` served |
| Agent → containerised backend | sample accepted |
| Persistence | data kept across `restart` and `down` / `up` |

Note: both test containers share Docker Desktop's Linux VM, so their CPU and memory figures are
the same machine's. On separate servers or VMs each agent reports its own.

### Repeating the live check

```bash
# Ubuntu 24.04 host with systemd, in Docker
cat > Dockerfile.ubuntu <<'EOF'
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends systemd systemd-sysv python3 procps ca-certificates
CMD ["/sbin/init"]
EOF
docker build -t sentineleye-test/ubuntu-systemd -f Dockerfile.ubuntu .
docker run -d --name node1 --privileged --cgroupns=host -v /sys/fs/cgroup:/sys/fs/cgroup:rw sentineleye-test/ubuntu-systemd
docker cp agent node1:/root/agent
docker exec -it node1 bash -c "cd /root/agent && ./install.sh --url http://host.docker.internal:8000 --server-id <id>"

# Generate load for ~75 s and watch the alert open and recover
docker exec -d node1 bash -c 'for i in $(seq $(nproc)); do (timeout 75 sh -c "while :; do :; done" &); done'

# Simulate an outage
docker exec node1 systemctl stop sentineleye-agent     # offline after 90 s
docker exec node1 systemctl start sentineleye-agent    # recovers on the next report
```
