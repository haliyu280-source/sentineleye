import { useState } from 'react'
import { ActivityList } from '../components/AlertTable'
import { AccessButton, BackendOffline } from '../components/AdminGate'
import { CopyField, ErrorNote, Meter, RefreshButton, StatusChip, StatusDot, StatusText, TopbarControls } from '../components/ui'
import { useAccess } from '../lib/access'
import { api } from '../lib/api'
import { formatPercent, STATUS_LABELS, timeAgo } from '../lib/format'
import { usePolling } from '../lib/usePolling'

const POLL_SECONDS = 15

function fleetStatus(counts) {
  if (!counts || counts.total === 0) return null
  if (counts.offline) return 'offline'
  if (counts.warning) return 'warning'
  if (counts.healthy) return 'healthy'
  return 'unknown'
}

function FleetStatusTile({ overview }) {
  const counts = overview.servers
  const status = fleetStatus(counts)
  const active = counts.total - counts.disabled
  let detail = 'No servers registered yet'
  if (status) detail = `${counts.healthy} of ${active} server${active === 1 ? '' : 's'} healthy`
  return (
    <section className={`tile tile-status tile-status-${status ?? 'pending'}`} aria-label="Infrastructure status">
      <div className="tile-head">
        <h2 className="label">Infrastructure</h2>
        {status && <StatusDot status={status} />}
      </div>
      <p className="status-word">{status ? STATUS_LABELS[status] : 'Empty'}</p>
      <p className="tile-foot">
        <span>{detail}</span>
        <span className="tile-foot-time">
          {overview.alerts.open + overview.alerts.acknowledged} active alert
          {overview.alerts.open + overview.alerts.acknowledged === 1 ? '' : 's'}
        </span>
      </p>
    </section>
  )
}

function ServersTile({ counts }) {
  const parts = ['healthy', 'warning', 'offline', 'unknown', 'disabled'].filter((k) => counts[k])
  return (
    <section className="tile" aria-label="Registered servers">
      <div className="tile-head">
        <h2 className="label">Servers</h2>
      </div>
      <p className="figure">
        <span className="figure-num">{counts.total}</span>
        <span className="figure-unit">registered</span>
      </p>
      <p className="tile-foot tile-foot-wrap">
        {parts.length ? (
          parts.map((k) => (
            <span key={k} className="count-pill">
              <StatusDot status={k} /> {counts[k]} {STATUS_LABELS[k].toLowerCase()}
            </span>
          ))
        ) : (
          <span>Register one to start monitoring</span>
        )}
      </p>
    </section>
  )
}

function AverageTile({ label, value, reporting }) {
  const available = typeof value === 'number'
  return (
    <section className="tile" aria-label={`${label} average: ${available ? `${formatPercent(value)} percent` : 'no data'}`}>
      <div className="tile-head">
        <h2 className="label">{label}</h2>
      </div>
      <p className="figure" aria-hidden="true">
        {available ? (
          <>
            <span className="figure-num num-update" key={value}>{formatPercent(value)}</span>
            <span className="figure-unit">%</span>
          </>
        ) : (
          <span className="figure-missing">No data</span>
        )}
      </p>
      <Meter value={available ? value : null} />
      <p className="tile-foot" aria-hidden="true">
        <span>{reporting ? `Average of ${reporting} reporting` : 'No servers reporting'}</span>
      </p>
    </section>
  )
}

function MiniMeter({ value, limit }) {
  if (typeof value !== 'number') return <span className="muted">—</span>
  return (
    <span className="mini-meter">
      <span className="mono">{formatPercent(value)}%</span>
      <Meter value={value} threshold={limit} warning={value >= limit} />
    </span>
  )
}

function ServerTable({ servers }) {
  if (servers.length === 0) {
    return <p className="log-empty">No servers are registered yet.</p>
  }
  return (
    <div className="table-wrap">
      <table className="log">
        <thead>
          <tr>
            <th scope="col">Server</th>
            <th scope="col">Status</th>
            <th scope="col">CPU</th>
            <th scope="col">Memory</th>
            <th scope="col">Disk</th>
            <th scope="col">Last report</th>
            <th scope="col">System</th>
          </tr>
        </thead>
        <tbody>
          {servers.map((s) => (
            <tr key={s.id} className="row-link">
              <td>
                <a className="table-link table-link-strong" href={`#/servers/${s.id}`}>
                  {s.name}
                </a>
                <span className="cell-sub">{s.hostname ?? 'awaiting first report'}</span>
              </td>
              <td>
                <StatusText status={s.status} />
                {s.active_alerts > 0 && <span className="cell-sub">{s.active_alerts} active alert{s.active_alerts > 1 ? 's' : ''}</span>}
              </td>
              <td><MiniMeter value={s.latest?.cpu_percent} limit={s.thresholds.cpu} /></td>
              <td><MiniMeter value={s.latest?.memory_percent} limit={s.thresholds.memory} /></td>
              <td><MiniMeter value={s.latest?.disk_percent} limit={s.thresholds.disk} /></td>
              <td className="mono">{timeAgo(s.last_seen_at)}</td>
              <td>
                {s.os_name ? `${s.os_name} ${s.os_version ?? ''}` : '—'}
                {s.environment && <span className="cell-sub">{s.environment}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RegisterServer({ onRegistered }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [environment, setEnvironment] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [created, setCreated] = useState(null)

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const result = await api('/api/servers', {
        method: 'POST',
        body: { name: name.trim(), ...(environment.trim() ? { environment: environment.trim() } : {}) },
      })
      setCreated(result)
      setName('')
      setEnvironment('')
      onRegistered()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (created) {
    const { server, agent_token: token } = created
    return (
      <section className="card card-highlight" aria-labelledby="registered-title">
        <div className="card-head">
          <div>
            <h2 id="registered-title" className="card-title">{server.name} registered</h2>
            <p className="card-sub">Copy the token now. It is stored only as a hash and will not be shown again.</p>
          </div>
          <button type="button" className="btn btn-quiet" onClick={() => setCreated(null)}>Done</button>
        </div>
        <dl className="kv">
          <dt>Server id</dt>
          <dd className="mono">{server.id}</dd>
          <dt>Agent token</dt>
          <dd><CopyField value={token.token} label="Agent token" /></dd>
          <dt>Install on the server</dt>
          <dd>
            <CopyField
              value={`sudo ./install.sh --url ${window.location.origin} --server-id ${server.id}`}
              label="Install command"
            />
            <p className="muted small">
              Run from the repository's <code className="inline-code">agent/</code> folder; it asks for the token. Use an
              address the server can reach, over HTTPS in production.
            </p>
          </dd>
        </dl>
      </section>
    )
  }

  if (!open) {
    return (
      <button type="button" className="btn btn-primary" onClick={() => setOpen(true)}>
        Register server
      </button>
    )
  }

  return (
    <form className="card form-inline" onSubmit={submit} aria-label="Register a server">
      <label className="field">
        <span className="field-label">Name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="web-01" required maxLength={100} autoFocus />
      </label>
      <label className="field">
        <span className="field-label">Environment (optional)</span>
        <input value={environment} onChange={(e) => setEnvironment(e.target.value)} placeholder="production" maxLength={50} />
      </label>
      <div className="form-actions">
        <button type="submit" className="btn btn-primary" disabled={busy || !name.trim()}>
          {busy ? 'Registering…' : 'Register'}
        </button>
        <button type="button" className="btn btn-quiet" onClick={() => setOpen(false)}>Cancel</button>
      </div>
      {error && <p className="field-error" role="alert">{error}</p>}
    </form>
  )
}

export default function Fleet() {
  const { isAdmin } = useAccess()
  const { data, error, loading, updatedAt, refresh } = usePolling(async () => {
    const [overview, servers, activity] = await Promise.all([
      api('/api/overview'),
      api('/api/servers'),
      api('/api/alert-events?limit=8'),
    ])
    return { overview, servers, activity }
  }, POLL_SECONDS)

  const status = data ? fleetStatus(data.overview.servers) : null

  if (error?.status === 0) return <BackendOffline onRetry={refresh} loading={loading} />

  return (
    <>
      <TopbarControls>
        {status && <StatusChip status={status} />}
        <RefreshButton onClick={refresh} loading={loading} label={updatedAt ? 'Refresh' : '…'} />
      </TopbarControls>

      <main className="page">
        <div className="page-head page-head-split">
          <div>
            <h1>Infrastructure</h1>
            <p className="page-sub">
              Every server reporting to this SentinelEye instance
              {updatedAt && <> · updated {updatedAt.toLocaleTimeString()}</>}
            </p>
          </div>
          <AccessButton />
        </div>

        <ErrorNote error={error} onRetry={refresh} />

        {data && (
          <>
            <div className={`tiles tiles-five ${error ? 'stale' : ''}`}>
              <FleetStatusTile overview={data.overview} />
              <ServersTile counts={data.overview.servers} />
              <AverageTile label="CPU" value={data.overview.averages.cpu} reporting={data.overview.averages.reporting_servers} />
              <AverageTile label="Memory" value={data.overview.averages.memory} reporting={data.overview.averages.reporting_servers} />
              <AverageTile label="Disk" value={data.overview.averages.disk} reporting={data.overview.averages.reporting_servers} />
            </div>

            <section className="card" aria-labelledby="servers-title">
              <div className="card-head">
                <div>
                  <h2 id="servers-title" className="card-title">Servers</h2>
                  <p className="card-sub">
                    Marked offline after {data.overview.heartbeat_timeout_seconds}s without a report
                  </p>
                </div>
                {isAdmin && <RegisterServer onRegistered={refresh} />}
              </div>
              <ServerTable servers={data.servers} />
            </section>

            <section className="card" aria-labelledby="activity-title">
              <div className="card-head">
                <div>
                  <h2 id="activity-title" className="card-title">Recent alert activity</h2>
                  <p className="card-sub">
                    <a className="table-link" href="#/alerts">Open the alert centre</a>
                  </p>
                </div>
              </div>
              <ActivityList events={data.activity} />
            </section>
          </>
        )}

        {!data && !error && <div className="tiles tiles-five"><section className="tile skeleton" aria-hidden="true" /></div>}
      </main>
    </>
  )
}
