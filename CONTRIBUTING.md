# Contributing

SentinelEye is a personal portfolio project and is not open for outside contributions; see
[LICENSE](LICENSE). These notes describe how the project is worked on.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
npm --prefix frontend install
cp .env.example .env    # set SENTINELEYE_ADMIN_TOKEN
```

## Before committing

```bash
.venv/bin/python -m pytest
npm --prefix frontend run lint
npm --prefix frontend run build
bash -n sentinel.sh agent/install.sh agent/uninstall.sh
```

## Conventions

- `GET /api/health` and its fields are a public contract. Add fields; never rename or remove them.
- `sentinel.sh` must keep working on its own on macOS and Linux, including its exit codes
  (0 healthy, 1 warning).
- The agent uses the Python standard library only.
- Configuration comes from environment variables; nothing secret goes into code, images or logs.
- New behaviour comes with tests. Tests that use made-up metric values say so.
- Timestamps are UTC in storage and in the API.
