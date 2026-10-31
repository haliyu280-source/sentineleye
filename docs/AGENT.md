# Agent installation guide

The SentinelEye agent is a small Python program that reports a Linux server's CPU, memory, disk
and uptime to the central backend. It uses only the Python standard library.

Supported: Linux with systemd and Python 3.10 or newer. Tested on **Ubuntu 24.04 LTS**.
Not supported: Windows, macOS.

## 1. Register the server

In the dashboard: **Fleet → Register server**. Or with the API:

```bash
curl -s -X POST https://monitor.example.com/api/servers \
  -H "Authorization: Bearer $SENTINELEYE_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "web-01", "environment": "production"}'
```

Note the `server.id` and `agent_token.token` from the response. **The token is only shown once**;
the backend keeps only a hash of it. If it is lost, reissue it (step 5).

## 2. Install

Copy the repository's `agent/` folder to the server (for example with `git clone` or `scp`), then:

```bash
cd agent
sudo ./install.sh --url https://monitor.example.com --server-id 3
```

The installer asks for the token without echoing it. To script the install, pass the token in the
environment instead:

```bash
sudo SENTINELEYE_TOKEN='se_…' ./install.sh --url https://monitor.example.com --server-id 3
```

Options: `--interval SECONDS` (default 30), `--reconfigure` (replace an existing config),
`--allow-http` (see *Plain HTTP* below).

What it does:

1. Creates the system user `sentineleye` (no login shell, no home directory).
2. Copies the agent to `/opt/sentineleye-agent`, owned by root and read-only for the service.
3. Writes `/etc/sentineleye-agent/agent.env`, owner `root`, group `sentineleye`, mode `640`.
4. Sends one test sample as the `sentineleye` user and stops if the backend rejects it.
5. Installs and (re)starts `sentineleye-agent.service`.

The server appears as *Healthy* on the Fleet page within one interval.

## Configuration

`/etc/sentineleye-agent/agent.env`:

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `SENTINELEYE_URL` | yes | | Backend base URL, e.g. `https://monitor.example.com` |
| `SENTINELEYE_SERVER_ID` | yes | | Numeric id from registration |
| `SENTINELEYE_TOKEN` | yes | | Agent token `se_<id>_<secret>` |
| `SENTINELEYE_INTERVAL` | | `30` | Seconds between samples (5–3600) |
| `SENTINELEYE_TIMEOUT` | | `10` | Per-request timeout in seconds |
| `SENTINELEYE_MAX_RETRIES` | | `4` | Retries per sample for network errors, 5xx and 429 |
| `SENTINELEYE_DISK_PATH` | | `/` | Filesystem to report |
| `SENTINELEYE_CA_BUNDLE` | | | PEM file of a private CA that signed the backend certificate |
| `SENTINELEYE_ALLOW_HTTP` | | `false` | Allow plain HTTP to a non-local host |

After editing it: `sudo systemctl restart sentineleye-agent`.

### Plain HTTP

The agent refuses to send its token over `http://` unless the host is `localhost`, `127.0.0.1`,
`::1` or `host.docker.internal`. `SENTINELEYE_ALLOW_HTTP=true` overrides this for isolated test
networks only: anyone on the path could read the token.

## Operating the service

```bash
systemctl status sentineleye-agent
sudo systemctl stop sentineleye-agent
sudo systemctl start sentineleye-agent
sudo systemctl restart sentineleye-agent
journalctl -u sentineleye-agent -f            # live log
journalctl -u sentineleye-agent --since today
```

Check what the agent would send, without sending anything:

```bash
cd /opt/sentineleye-agent && python3 -m sentineleye_agent --print
```

Send one sample by hand with the service's configuration:

```bash
sudo -u sentineleye env PYTHONPATH=/opt/sentineleye-agent \
  python3 -m sentineleye_agent --config /etc/sentineleye-agent/agent.env --once
```

### Resources and sandboxing

The unit runs the agent as `sentineleye` with `NoNewPrivileges`, `ProtectSystem=strict`,
`ProtectHome`, `PrivateTmp`, `PrivateDevices`, an empty capability set, and limits of 64 MB memory
and 10 % of one CPU. In testing it used about 23 MB of memory. `systemd-analyze security
sentineleye-agent` rates the unit 4.0 ("OK").

## Rotating or revoking a token

- **Rotate**: in the dashboard open the server → *Settings → Agent tokens → Reissue token*, or
  `POST /api/servers/{id}/tokens/reissue`. All older tokens stop working immediately. Then on the
  server:

  ```bash
  cd agent && sudo ./install.sh --url https://monitor.example.com --server-id 3 --reconfigure
  ```

- **Revoke** a single token with *Revoke*, or `POST /api/servers/{id}/tokens/{token_id}/revoke`.
  The agent logs `Delivery rejected: HTTP 401` and does not retry until its next interval.

## Troubleshooting

| Symptom in `journalctl` | Cause | Fix |
|---|---|---|
| `Cannot start: SENTINELEYE_TOKEN is missing or not a valid agent token` | Token missing or mistyped | Re-run `install.sh --reconfigure` |
| `Refusing to send the agent token over plain HTTP` | `http://` URL to a remote host | Use `https://` |
| `Delivery rejected: HTTP 401` | Token revoked, reissued, expired or wrong | Reissue and reconfigure |
| `Delivery rejected: HTTP 403: Token is not valid for this server_id` | `SENTINELEYE_SERVER_ID` belongs to another server | Fix the id |
| `Delivery rejected: HTTP 403: This server is disabled` | Monitoring disabled in SentinelEye | Re-enable it on the server page |
| `HTTP 422: collected_at is too old` / `in the future` | Clock differs from the backend by more than 5 minutes | Enable time sync: `timedatectl set-ntp true` |
| `Cannot reach backend: …` with retries | DNS, firewall, proxy or backend down | `curl -v https://monitor.example.com/healthz` from the server |
| `CERTIFICATE_VERIFY_FAILED` | Backend uses a private CA | Set `SENTINELEYE_CA_BUNDLE` |

The server page in the dashboard also shows the agent's last delivery error and how many
deliveries failed before the last successful one.

## Uninstall

```bash
cd agent
sudo ./uninstall.sh            # keeps /etc/sentineleye-agent
sudo ./uninstall.sh --purge    # also removes the config (and token) and the service user
```

Then revoke the server's token or delete the server in SentinelEye.
