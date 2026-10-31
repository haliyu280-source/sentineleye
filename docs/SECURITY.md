# Security

This document separates what the code **implements** from what an operator is **recommended**
to do around it. Nothing in the "Recommended" sections is enforced by SentinelEye itself.

## Access levels

| Caller | Credential | Can do |
|---|---|---|
| Agent | Its own agent token | `POST /api/agent/metrics` for its own server, nothing else |
| Admin | `SENTINELEYE_ADMIN_TOKEN` | Everything: read, register servers, tokens, limits, alert actions, delete |
| Anonymous visitor, public mode on | none | Read servers, metrics, history, overview and alerts |
| Anonymous visitor, public mode off (default) | none | `GET /api/health`, `GET /api/meta`, `GET /healthz`, API docs |

## Implemented controls

### Agent tokens

- **Format.** `se_<token_id>_<secret>`: `token_id` is 16 hex characters from
  `secrets.token_hex(8)`; `secret` is 43 characters from `secrets.token_urlsafe(32)` (256 bits).
  Both come from Python's `secrets` module, which uses the operating system's cryptographically
  secure random source.
- **Storage.** Only `SHA-256(secret)` is stored, with the `token_id` for lookup. The full token is
  returned once, in the response to registration, `POST /tokens` or `/tokens/reissue`, and never
  again: token listings show ids and dates only.
- **Why a fast hash is acceptable.** Hashing protects against someone who obtains a copy of the
  database. Slow hashes such as bcrypt exist to make guessing low-entropy human passwords
  expensive. A 256-bit random secret cannot be guessed, so SHA-256 gives the same protection
  without the cost.
- **Verification.** The token's format is checked, the record is found by `token_id`, and the
  hash of the presented secret is compared with `hmac.compare_digest` (constant time).
- **Uniform failures.** Unknown, wrong, revoked and expired tokens all get the same
  `401 Invalid, revoked or expired agent token`, so responses do not reveal which case applied.
- **Revocation.** `POST /api/servers/{id}/tokens/{token_id}/revoke` sets `revoked_at`; the token is
  refused from the next request.
- **Reissue.** `POST /api/servers/{id}/tokens/reissue` revokes every active token for the server and
  issues one replacement. `POST /api/servers/{id}/tokens` issues an extra token without revoking
  others, for a staged migration.
- **Expiry.** Off by default. With `SENTINELEYE_TOKEN_TTL_DAYS` set, new tokens get an
  `expires_at` and are refused after it.

### Server identity binding

Each token belongs to one server. The sample's `server_id` must equal the token's server, or the
request is refused with 403, so an agent cannot submit data for another machine even with a
valid token. A disabled server's agent is refused with 403.

### Timestamps and replay protection

- `collected_at` must include a time zone.
- It must be within `SENTINELEYE_MAX_CLOCK_SKEW_SECONDS` (300) of the backend's clock, in either
  direction; otherwise 422 (`too old` or `in the future`).
- It must be strictly newer than the server's latest stored sample; otherwise 409.

Together these stop a captured request from being replayed later (too old, or not newer) and
stop duplicates from a retry. They do not prove the request came from the agent at that moment:
there are no request signatures or nonces. Within the 5-minute window, a captured *newer*
request could still be submitted once, which is why HTTPS is required in production.

### Request validation

Agent payloads are validated by Pydantic with `extra="forbid"`: unknown fields are rejected,
percentages must be 0–100, byte counts non-negative and bounded, `used` and `available` cannot
exceed `total`, hostnames must match `^[A-Za-z0-9._-]+$`, and strings have maximum lengths.
Management payloads (server names, limits, notes) are validated the same way. Invalid requests
get 422.

### Request size

`BodySizeLimit` middleware refuses `POST`, `PUT` and `PATCH` bodies over
`SENTINELEYE_MAX_REQUEST_BYTES` (65536) with 413. It checks `Content-Length` and also counts the
bytes actually received, so a request without the header is still capped.

### Rate limiting

| Limit | Default | Setting |
|---|---|---|
| Reports per agent token | 30 per minute | `SENTINELEYE_AGENT_RATE_LIMIT_PER_MINUTE` |
| Failed admin or agent authentication per client address | 10 per minute | `SENTINELEYE_ADMIN_AUTH_FAILURES_PER_MINUTE` |

Exceeding either returns 429. The limiter is an in-memory sliding window, so limits apply per
backend process and reset on restart.

### Administrative access

- Management endpoints require `Authorization: Bearer <SENTINELEYE_ADMIN_TOKEN>`.
- If `SENTINELEYE_ADMIN_TOKEN` is not set, they return 503 instead of being open.
- The comparison hashes both values and uses a constant-time compare, so neither the token nor
  its length leaks through timing.
- The dashboard keeps the admin token in `sessionStorage` for the current tab and drops it when
  the API rejects it or the admin signs out.

### Public read-only access

Off by default. With `SENTINELEYE_PUBLIC_DASHBOARD=true`:

- Read endpoints (servers, status, latest metrics, history, overview, alerts, alert events)
  answer without a token.
- Everything that changes state, and every token endpoint, still requires the admin token.
- Anonymous responses omit `last_agent_error`, because an agent's raw error text can contain
  internal host names or addresses.
- A request that sends a wrong token is still rejected, so a stale dashboard session notices.

Turning it on makes the monitored servers' names, OS versions and usage public.

### Restricted agent permissions

The installer and systemd unit (`agent/sentineleye-agent.service`) run the agent:

- as the system user `sentineleye`, with no login shell and no home directory;
- from `/opt/sentineleye-agent`, owned by root and not writable by the service;
- with its configuration in `/etc/sentineleye-agent/agent.env`, mode 640, owner root, group
  `sentineleye`;
- under `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`,
  `PrivateDevices`, `ProtectKernelTunables`, `ProtectKernelModules`, `ProtectControlGroups`,
  `RestrictSUIDSGID`, an empty `CapabilityBoundingSet`, `RestrictAddressFamilies` limited to
  IPv4, IPv6 and Unix sockets, `MemoryMax=64M` and `CPUQuota=10%`.

`systemd-analyze security` rated the unit 4.0 ("OK") on Ubuntu 24.04. The installer never takes
the token as a command-line argument (it would appear in shell history and the process list): it
reads `SENTINELEYE_TOKEN` from the environment or prompts without echo.

### No remote command execution

The agent only reads `/proc`, `/etc/os-release` and filesystem statistics, and sends them. It
opens no listening port and accepts no instructions from the backend; the only data it reads from
a response is whether the sample was accepted. The backend has no endpoint that runs commands on
monitored servers. The only command the backend runs is its own `sentinel.sh`, locally, for
`GET /api/health`.

### Secrets handling

- Tokens are not logged by the agent or the backend. The agent's configuration object redacts
  the token from its text representation.
- `.env` is excluded by `.gitignore` and `.dockerignore`; the Docker image contains no secrets and
  reads configuration from the environment at runtime.
- The agent refuses to send its token over plain HTTP to a non-local address unless
  `SENTINELEYE_ALLOW_HTTP=true`.

### Container

The Compose service runs as uid 10001 with a read-only root filesystem, a `tmpfs` for `/tmp`,
all Linux capabilities dropped and `no-new-privileges`, and publishes its port on `127.0.0.1` by
default.

## Not implemented

- **TLS termination.** The backend serves plain HTTP.
- **User accounts and roles.** One shared admin token; no per-person audit trail beyond the
  `admin` actor on alert events.
- **Request signing, nonces or mutual TLS** for agents.
- **Distributed rate limiting.** Limits are per process.
- **Automatic token rotation.** Rotation is manual (reissue).
- **Encryption at rest** for the SQLite database.
- **CSRF protection.** Not needed for the current design, because the admin token is sent as a
  header, not a cookie.

## Recommended for production

- Put a reverse proxy with a valid certificate in front of the backend (example in
  [DEPLOYMENT.md](DEPLOYMENT.md)) and point agents at `https://`.
- Keep the backend port bound to `127.0.0.1` so it is reachable only through the proxy, and set
  `FORWARDED_ALLOW_IPS` so the client addresses used for rate limiting are real.
- Use a long random admin token (`python3 -c "import secrets; print(secrets.token_urlsafe(32))"`),
  keep `.env` at mode 600, and change it if it may have been exposed.
- Leave `SENTINELEYE_PUBLIC_DASHBOARD` off unless the monitored servers are meant to be public.
- Keep the clocks of the backend and agents synchronised (NTP); samples more than 5 minutes off
  are rejected.
- Set `SENTINELEYE_TOKEN_TTL_DAYS` if tokens should expire, and revoke a server's token when it is
  retired.
- Back up the database volume and restrict who can read it: it contains token hashes and the
  fleet's history.

## Reporting a vulnerability

This is a personal portfolio project. Please contact the author privately rather than opening a
public issue.
