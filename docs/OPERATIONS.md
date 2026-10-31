# Operations runbook

How to run SentinelEye day to day. It assumes the backend is deployed (see
[DEPLOYMENT.md](DEPLOYMENT.md)) and that you have the admin token.

Examples use the API with these variables; every step can also be done in the dashboard.

```bash
API=https://monitor.example.com
ADMIN="Authorization: Bearer $SENTINELEYE_ADMIN_TOKEN"
```

## Status reference

| Status | Meaning |
|---|---|
| **Healthy** | Reporting, and the latest sample is under every limit |
| **Warning** | Reporting, and a metric is at or above its limit (an incident opens after two consecutive breaches) |
| **Offline** | Reported before, but nothing for longer than the heartbeat timeout (90 s by default) |
| **Unknown** | Registered, but its agent has never reported |
| **Disabled** | Monitoring switched off; its agent's reports are refused |

| Incident | Opens when | Severity |
|---|---|---|
| High CPU / memory / disk | Two consecutive samples at or above the limit | warning |
| Server unavailable | No report for longer than the heartbeat timeout | critical |

Default limits: CPU 80 %, memory 85 %, disk 80 %.

## 1. Register a server and get its token

Dashboard: sign in (*Admin sign in*), open **Fleet**, choose **Register server**, enter a name and
optionally an environment. The next panel shows the server id, the agent token and the install
command.

API:

```bash
curl -s -X POST $API/api/servers -H "$ADMIN" -H "Content-Type: application/json" \
  -d '{"name": "web-01", "environment": "production", "thresholds": {"disk": 90}}'
```

The response contains `server.id` and `agent_token.token`. **Copy the token now**: only its hash is
stored and it cannot be shown again. If it is lost, reissue it (section 10).

## 2. Install the agent

On the server, from a copy of the repository's `agent/` folder:

```bash
cd agent
sudo ./install.sh --url https://monitor.example.com --server-id 3
```

Paste the token when asked. The installer sends one test sample and stops with an error if the
backend refuses it, so a successful run means the server, token and URL are correct.

## 3. Confirm the first report

- The server changes from *Unknown* to *Healthy* (or *Warning*) on the Fleet page within one
  interval (30 s).
- On the server: `systemctl status sentineleye-agent` shows `active (running)`, and
  `journalctl -u sentineleye-agent -n 20` shows `SentinelEye agent 1.0.0 reporting to ...`
  without errors.
- API: `curl -s $API/api/servers/3/status -H "$ADMIN"` shows `"status": "healthy"` and a recent
  `last_seen_at`.

If it stays *Unknown*, follow the agent troubleshooting table in
[DEPLOYMENT.md](DEPLOYMENT.md#troubleshooting).

## 4. Monitor the fleet

- **Fleet** shows overall status, counts per status, average CPU, memory and disk across reporting
  servers, each server's current usage against its limits, and the latest alert activity.
- **Alerts** lists active incidents; switch to *Resolved* or *All* for history. Expand an incident
  to see its timeline.
- Pages refresh every 15 seconds.

API equivalents: `GET /api/overview`, `GET /api/servers`, `GET /api/alerts?status=active`.

## 5. Investigate high CPU

1. Open the server's page. Check the **History** chart with *CPU* selected: a short spike, a
   step change at a known time (deployment, cron job) or a slow climb?
2. Compare 1h and 24h to see whether it is new.
3. On the server, find the cause:

   ```bash
   top -o %CPU
   ps -eo pid,user,%cpu,etime,cmd --sort=-%cpu | head
   uptime                      # load average versus CPU count
   nproc
   ```

4. Act on the cause (a runaway process, a job scheduled at a busy time, a server that needs more
   capacity). If sustained high CPU is normal for this machine, raise its limit (section 12)
   rather than living with a permanent incident.
5. **Acknowledge** the incident while you work on it (section 8). It closes by itself as
   *recovered* when CPU drops below the limit.

## 6. Investigate memory pressure

SentinelEye's memory figure is `MemTotal − MemAvailable`, so reclaimable cache is not counted.
A high value means real pressure.

```bash
free -h
ps -eo pid,user,%mem,rss,cmd --sort=-%mem | head
journalctl -k | grep -i -E "out of memory|oom"     # processes killed by the kernel
swapon --show
```

Look for a process whose memory keeps growing (a leak), too many workers, or a machine that is
simply too small. Restart or reconfigure the offending service, or add memory. As with CPU, the
incident recovers by itself when usage falls below the limit.

## 7. Investigate disk usage

The agent reports the filesystem mounted at `/` (or `SENTINELEYE_DISK_PATH`).

```bash
df -h /
sudo du -xh --max-depth=1 / 2>/dev/null | sort -h | tail
sudo journalctl --disk-usage
ls -lhS /var/log | head
```

Common culprits are logs without rotation, old journal files, container images and volumes,
package caches and backups written to the root disk. Free space, set up rotation
(`sudo journalctl --vacuum-size=500M` for the journal), or grow the volume. The history chart with
*Disk* selected over 7 days shows how fast it is filling.

## 8. Acknowledge an incident

Acknowledging says "someone is on it". The incident stays active and keeps updating, and no
duplicate opens.

- Dashboard (signed in): **Alerts** → **Acknowledge** on the incident.
- API:

  ```bash
  curl -s -X POST $API/api/alerts/12/acknowledge -H "$ADMIN" -H "Content-Type: application/json" \
    -d '{"note": "Investigating a log loop on web-01"}'
  ```

Only *open* incidents can be acknowledged.

## 9. Resolve an incident

Threshold and availability incidents normally **resolve themselves** as *recovered* when the
condition clears. Resolve one manually only when you know it is no longer relevant.

- Dashboard: **Alerts** → **Resolve**.
- API:

  ```bash
  curl -s -X POST $API/api/alerts/12/resolve -H "$ADMIN" -H "Content-Type: application/json" \
    -d '{"note": "Limit raised for this batch host"}'
  ```

If the condition is still present, a new incident opens after the next two breaching samples.

## 10. Handle an offline server

A *Server unavailable* incident means no report for longer than the heartbeat timeout. From the
backend's side, a powered-off server, a network problem and a stopped agent look the same, so
check in order:

1. **Is the machine up?** `ping` it, or check your hosting provider's console.
2. **Is the agent running?**

   ```bash
   systemctl status sentineleye-agent
   journalctl -u sentineleye-agent -n 50
   ```

3. **Can it reach the backend?** From the server:

   ```bash
   curl -sv https://monitor.example.com/healthz
   ```

4. **What does the agent log say?** `HTTP 401` means the token was revoked or replaced;
   `too old` or `in the future` means the clock is wrong; `Cannot reach backend` points to DNS,
   firewall or the backend itself.

When reports resume, the incident closes as *recovered*. The server page shows **Failed
deliveries** and **Last delivery error**, which the agent reports after a period it could not get
through; that distinguishes "the agent was running but could not reach us" from "the machine was
down".

If the **backend** was down, every server goes offline together once it is back, and each
recovers on its next report.

## 11. Revoke a compromised token

If a token may have leaked (copied into a ticket, a server was compromised, a laptop lost):

1. **Revoke it immediately.** Dashboard: server page → **Settings** → **Agent tokens** →
   **Revoke**. API:

   ```bash
   curl -s $API/api/servers/3/tokens -H "$ADMIN"                     # find the token_id
   curl -s -X POST $API/api/servers/3/tokens/5f2c1a9b0d3e4f61/revoke -H "$ADMIN"
   ```

   Requests with it are refused from that moment.

2. **Issue a replacement**, which also revokes any other active token for the server:

   ```bash
   curl -s -X POST $API/api/servers/3/tokens/reissue -H "$ADMIN"
   ```

3. **Install the new token** on the server:

   ```bash
   cd agent
   sudo ./install.sh --url https://monitor.example.com --server-id 3 --reconfigure
   ```

4. Check the server's history for samples you do not expect during the exposure window.

A leaked token can only submit metrics for that one server; it cannot read data or reach other
servers. If the **admin token** leaks, change `SENTINELEYE_ADMIN_TOKEN` in `.env` and restart the
backend.

## 12. Change limits

Dashboard: server page → **Settings** → enter limits → **Save limits**. Leave a field empty to use
the default. API:

```bash
curl -s -X PATCH $API/api/servers/3 -H "$ADMIN" -H "Content-Type: application/json" \
  -d '{"thresholds": {"cpu": 95, "memory": null}}'
```

`null` returns that metric to the default. New limits apply from the next sample.

## 13. Disable or remove a server

- **Disable** (keeps history; reports are refused; shows as *Disabled*; no offline incident):
  dashboard **Settings** → **Disable monitoring**, or

  ```bash
  curl -s -X PATCH $API/api/servers/3 -H "$ADMIN" -H "Content-Type: application/json" -d '{"enabled": false}'
  ```

- **Delete** (permanently removes the server, its tokens, metric history and incidents):
  dashboard **Settings** → **Delete server** and type the name to confirm, or

  ```bash
  curl -s -X DELETE $API/api/servers/3 -H "$ADMIN"
  ```

Then remove the agent from the machine with `sudo ./uninstall.sh --purge`.

## 14. Review history

On a server's page, **History** shows CPU, memory or disk for the last 1 hour, 6 hours, 24 hours
or 7 days. The dashed line is the current limit. Gaps in the line are periods with no reports.
Ranges with more than 360 samples are averaged into time buckets; the note under the chart says
how many samples and what bucket size.

```bash
curl -s "$API/api/servers/3/metrics?range=24h" -H "$ADMIN"
curl -s "$API/api/alert-events?server_id=3&limit=50" -H "$ADMIN"
```

Metrics older than the retention period (30 days by default) are deleted. Incidents and their
timelines are kept.

## Routine checks

- **Daily:** active incidents; servers in *Unknown* or *Offline* that should be reporting.
- **Weekly:** disk trends over 7 days; servers with a non-zero *Failed deliveries* count.
- **When retiring a server:** delete it (or disable it) and revoke its token.
- **Backups:** copy the database (see [DEPLOYMENT.md](DEPLOYMENT.md#database-persistence)).
