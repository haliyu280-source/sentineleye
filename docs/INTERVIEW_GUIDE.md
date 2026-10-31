# Interview guide

Notes for explaining SentinelEye in a technical interview. The answers are written the way a
junior cloud engineer who built the project would say them: specific about what was done, honest
about what was not. Use them to understand the reasoning, not to recite.

## The 30-second version

> SentinelEye is a self-hosted monitoring system for Linux servers. It started as a Bash script
> that checked one machine's CPU, memory and disk. I turned it into a platform: a small Python
> agent runs on each server and sends metrics every 30 seconds over HTTPS to a FastAPI backend.
> The backend authenticates the agent, stores the history in SQLite, works out whether each server
> is healthy, and opens incidents when a limit is crossed or a server stops reporting. A React
> dashboard shows it all. It has 92 automated tests and I tested it on Ubuntu 24.04 with real CPU
> load and by stopping agents to trigger outage alerts.

## Architecture

**Q: Walk me through the architecture.**

> There are three parts. On each monitored server there's an agent: a Python process run by
> systemd under its own unprivileged user. Every 30 seconds it reads `/proc` and the disk
> statistics, builds a JSON sample and POSTs it to the central backend with its token.
>
> The backend is a single FastAPI application. When a sample arrives it checks the token, checks
> that the token belongs to the server named in the sample, checks the timestamp, validates the
> values, stores the sample and runs the alert rules. A background task in the same process runs
> every 15 seconds to find servers that have gone quiet, and once an hour deletes old metrics.
>
> The data lives in SQLite through SQLAlchemy. The React dashboard is built into static files that
> FastAPI serves, and it polls the API every 15 seconds.

**Q: Why did you put everything in one backend process instead of microservices?**

> For tens of servers, one process is plenty, and it's much easier to run, test and debug. I kept
> the code split by responsibility, with routes, the alert engine, status logic and security in
> separate modules, so it could be pulled apart later if it needed to scale. Microservices would
> have added network calls and deployment complexity without solving a problem I actually had.

## Agents and Linux metrics

**Q: Why use an agent instead of polling servers from the centre?**

> Polling would mean the central server needs SSH access or an open port on every machine, which
> is a security risk and hard through firewalls and NAT. With an agent, each server only makes
> outbound HTTPS requests. It also gives a natural health signal: if a server stops pushing, that
> itself tells you something is wrong.

**Q: How does the agent collect metrics?**

> It reads Linux kernel interfaces directly. CPU comes from `/proc/stat`, memory from
> `/proc/meminfo`, uptime from `/proc/uptime`, the OS from `/etc/os-release`, and disk from the
> `statvfs` system call on the root filesystem. I used only the Python standard library, so
> there's nothing to install on the servers besides Python 3.

**Q: How do you calculate CPU usage?**

> `/proc/stat` doesn't give a percentage. It gives cumulative counters of time the CPUs have spent
> in each state since boot: user, system, idle, iowait and so on. One reading on its own is
> useless, so you take two readings and compare them. Idle time is idle plus iowait; total is the
> sum of the main fields. CPU usage is one minus the change in idle divided by the change in total,
> times 100. The agent keeps the previous reading between reports, so each figure is the average
> over the whole 30 seconds rather than a one-second snapshot.

**Q: And memory?**

> Used memory is `MemTotal` minus `MemAvailable`. The important part is not using `MemFree`:
> Linux uses spare memory for file cache, so `MemFree` is usually small even on a healthy server.
> `MemAvailable` is the kernel's estimate of what can be given to applications, including cache it
> can drop, so it reflects real memory pressure.

**Q: Disk?**

> From `statvfs`: total is blocks times block size, used is total blocks minus free blocks, and the
> percentage is used divided by used plus the space available to normal users. That's the same
> formula `df` uses, and in testing my numbers matched `df` exactly.

## Communication and authentication

**Q: How does the agent talk to the backend securely?**

> Over HTTPS. The backend itself serves plain HTTP, and in production it sits behind a reverse
> proxy like Caddy or nginx that terminates TLS. TLS encrypts the traffic so nobody on the network
> can read the token or the data, and the agent verifies the server's certificate so it knows it's
> talking to the real backend. The agent refuses to send its token over plain HTTP to anything
> except localhost unless you explicitly override it.

**Q: How does the backend authenticate agents?**

> Each server gets its own token when it's registered. It looks like `se_`, a public id, and a
> 256-bit random secret. The agent sends it as a Bearer token. The backend looks up the record by
> the public id, hashes the secret with SHA-256 and compares it to the stored hash in constant
> time. Then it checks the token isn't revoked or expired and that the server is enabled. Finally
> it checks that the server id in the payload is the token's own server, so a valid token can't be
> used to submit data for a different machine.

**Q: Why hash the tokens?**

> If someone gets a copy of the database, from a backup or a misconfigured volume, they shouldn't
> be able to use what they find to impersonate agents. With only hashes stored, the database
> doesn't contain working tokens. That's also why the token is only shown once, when it's issued.

**Q: Why SHA-256 and not bcrypt like for passwords?**

> Bcrypt is deliberately slow to make guessing weak human passwords expensive. These secrets are
> 256 bits of randomness, so there's nothing to guess, and a slow hash would only make every
> request more expensive. A fast cryptographic hash is the standard approach for random API keys.

## Data integrity

**Q: How do you protect against replayed requests?**

> Every sample includes the time it was collected. The backend rejects samples more than five
> minutes older or newer than its own clock, and rejects any sample that isn't newer than the
> last one it stored for that server. So if someone captured a request and sent it again, it would
> be a duplicate or too old. It's not perfect: there's no request signing, so within the
> five-minute window a captured request that is newer than the last sample could be accepted once.
> That's why HTTPS matters, since it stops requests being captured in the first place. Signed
> requests with a nonce would be the next step.

**Q: What validation happens on incoming data?**

> The payload is a strict Pydantic model: unknown fields are rejected, percentages must be between
> 0 and 100, used can't exceed total, hostnames must match a safe pattern, and strings have length
> limits. Bodies over 64 KB are refused before parsing, and each agent is limited to 30 reports a
> minute. The agent also validates its own sample before sending, so a bug on the server side is
> caught early.

## Availability and alerting

**Q: How does offline detection work?**

> Every accepted sample updates the server's `last_seen_at`. A background job checks every 15
> seconds for enabled servers whose last report is older than 90 seconds, which is three missed
> reports, and opens a critical "server unavailable" incident. The server's status is also worked
> out on every read from that timestamp, so the dashboard shows it as offline straight away even
> between job runs. When the next sample arrives, the incident closes as recovered. A server that
> has never reported is shown as "unknown" instead, because "never set up" and "stopped working"
> are different problems.

**Q: Why require two consecutive bad readings before alerting?**

> To avoid false alarms. CPU in particular spikes briefly all the time: a cron job, a deploy, a
> backup. If every single spike opened an incident, people would start ignoring alerts. Requiring
> two consecutive breaches means the problem lasted at least one full interval. The dashboard
> still shows the server as "warning" from the first breach, so the information isn't hidden;
> only the incident waits. The number is configurable.

**Q: How do you avoid duplicate incidents?**

> There's only ever one active incident per server and type. While the condition continues, each
> new sample updates the existing incident, its last value, peak and last-seen time, instead of
> creating a new one. When the metric drops below the limit, the incident is resolved as
> recovered. I also enforced it in the database with a partial unique index on server and type
> where the status isn't resolved, so even two requests arriving at the same moment can't create
> two. The tests check this, and when I deliberately broke the check in the code, the tests
> failed on the database constraint.

**Q: What is the incident lifecycle?**

> Open, then optionally acknowledged, then resolved. Acknowledged means someone is working on it;
> it stays active and keeps updating. Resolved happens either automatically, when the metric
> recovers or the agent reports again, or manually by an admin. Every step is stored as an event
> with who did it, so each incident has a timeline.

## Deployment

**Q: How is Docker used?**

> The central backend ships as a Docker image built in two stages: a Node stage builds the React
> dashboard, then a slim Python image installs the backend and copies in the built files, so one
> container serves both. Docker Compose runs it with a named volume for the SQLite database, a
> health check against `/healthz`, a restart policy and log rotation. The container runs as a
> non-root user with a read-only filesystem and all Linux capabilities dropped. Secrets come from
> an `.env` file at runtime and are never baked into the image. The agents are not containerised;
> they're installed directly on each server with systemd, because they need to see the host.

**Q: What happens if the backend goes offline?**

> The agents keep collecting. Each sample is retried a few times with exponential backoff, capped
> at half the interval, and then dropped, so samples during the outage are lost. The agent doesn't
> buffer them to disk. It does count the failures, and when the backend is back, the next sample
> reports how many deliveries failed and the last error, which the dashboard shows. Every server
> will show as offline until it reports again, and they all recover on their next report. If I
> wanted no gaps, I'd add a small on-disk buffer in the agent and send the backlog after
> reconnecting.

## Scaling

**Q: How would this scale to 100 servers?**

> At 100 servers with a 30-second interval that's about 3 or 4 requests a second, which one
> FastAPI process and SQLite can handle. The main thing I'd watch is the database: that's about
> 290,000 rows a day, so the 30-day retention and the index on server and time matter. I'd
> probably move to PostgreSQL at this point for better concurrent writes. The models are written
> through SQLAlchemy so that's mostly a configuration change, but I haven't tested it yet.

**Q: And 1,000 servers?**

> That's 30-plus writes a second and around 3 million rows a day, so a few things would need to
> change:
> - **Database:** PostgreSQL with TimescaleDB or a dedicated time-series database, and downsampling
>   old data into hourly averages instead of keeping every sample.
> - **Multiple backend instances** behind a load balancer. The rate limiter is in memory and the
>   offline-check job runs inside the process, so they'd need to move to shared storage like Redis
>   and a single scheduler, or the job would run once per instance.
> - **The dashboard** currently loads the whole server list and computes status per server on each
>   request, so it would need pagination and probably cached aggregates.
> - **Possibly a queue** between ingestion and the alert engine, so bursts don't slow down the
>   agents.

## Limitations and improvements

**Q: What are the limitations?**

> - Agents are Linux only and tested on Ubuntu 24.04 only.
> - HTTPS depends on a reverse proxy; the app doesn't do TLS itself.
> - There's one shared admin token instead of user accounts.
> - Only SQLite has been tested, and there are no schema migrations.
> - One filesystem per agent.
> - From the backend's side, a dead server and a broken network look the same.
> - Agents in containers see the host's CPU and memory, which I noticed in testing: two test
>   containers alerted together because they share the same VM.
> - E-mail alerts are tested with a simulated mail server only.

**Q: What would you improve next?**

> Database migrations with Alembic and a tested PostgreSQL setup; user accounts with roles instead
> of the single admin token; signed agent requests for stronger replay protection; an on-disk
> buffer in the agent so outages don't leave gaps; monitoring more than one filesystem and network
> traffic; and webhook notifications for Slack or Teams alongside e-mail.

## Questions about the process

**Q: What was the hardest bug?**

> A good one came from live testing rather than unit tests. When I rotated an agent's token and
> re-ran the installer, the new token was written to the config file and the installer's test
> sample worked, but the running service kept failing with 401. The installer used `systemctl
> enable --now`, which starts a stopped service but doesn't restart a running one, so the agent
> still had the old token in memory. I changed it to restart the service. It's a good example of
> why I tested on a real systemd host and not only with mocks.

**Q: How did you test it?**

> In two layers. There are 92 automated pytest tests: the backend tests run against a fresh SQLite
> database for each test, and the agent tests parse recorded `/proc` files, so they're fast and
> repeatable. Two end-to-end tests run the real agent code against the real backend in process.
> Then I tested live on Ubuntu 24.04 containers running systemd: I used the real installer, put
> real CPU load on the machine to trigger and recover alerts, stopped the agent to trigger an
> offline alert, revoked and reissued tokens, and checked the Docker deployment. I kept those
> clearly separate in the docs, so it's obvious which results used controlled values and which
> used real metrics.

**Q: Did you use any existing monitoring tools?**

> No, the point was to understand how they work. The design follows the same ideas as tools like
> Prometheus's node exporter or Datadog's agent: an agent reading `/proc`, a central store,
> threshold rules with a "for" duration, and deduplicated incidents. In a real job I'd use those
> tools, but building a small version taught me what they're doing underneath.

## Concepts worth knowing

- **`/proc`**: a virtual filesystem through which the Linux kernel exposes process and system
  information as text files. Nothing is stored on disk.
- **Cumulative counters**: many system metrics (CPU time, network bytes) only ever increase. Rates
  and percentages come from the difference between two readings.
- **TLS termination at a reverse proxy**: the proxy handles certificates and encryption and
  forwards plain HTTP to the app on the same host or private network.
- **Bearer tokens**: credentials sent in the `Authorization` header; whoever holds the token can
  use it, which is why transport encryption and revocation matter.
- **Constant-time comparison**: comparing secrets in a way that always takes the same time, so an
  attacker can't learn how many characters matched from response times.
- **Idempotency and deduplication**: designing operations so that repeats (retries, replays,
  repeated breaches) don't create duplicate effects.
- **systemd sandboxing**: unit options such as `ProtectSystem` and `NoNewPrivileges` that restrict
  what a service can do even if it is compromised.
- **Heartbeat monitoring**: detecting failure by the absence of expected messages rather than by
  an explicit error.
