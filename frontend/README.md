# SentinelEye dashboard

React + Vite single-page app for SentinelEye. In production it is built into `dist/` and served by
the FastAPI backend from the same origin.

```bash
npm install
npm run dev      # http://localhost:5173, proxies /api to http://127.0.0.1:8000
npm run lint
npm run build
```

Point the dev proxy at another backend with `SENTINELEYE_API_URL=http://host:port npm run dev`.

## Structure

```
src/
  App.jsx              shell: top bar, navigation, admin gate, footer
  pages/
    Fleet.jsx          overview, server list, registration
    ServerDetail.jsx   one server: usage, history, agent, alerts, settings, tokens
    Alerts.jsx         incidents and alert history
    CentralServer.jsx  Central server page: the machine running SentinelEye (GET /api/health)
  components/          shared UI: meters, status chips, charts, alert table, sign-in
  lib/                 API client, hash router, polling, formatting
```

Routes are hash-based (`#/`, `#/servers/3`, `#/alerts`, `#/central`, `#/signin`) so the build stays
a set of static files. When the backend runs in public mode the fleet pages open without signing
in and management controls appear only for the admin.
