import { useState } from 'react'
import { AlertTable } from '../components/AlertTable'
import { LineChart } from '../components/LineChart'
import { CopyField, ErrorNote, Meter, RefreshButton, Segmented, StatusChip, StatusDot, TopbarControls } from '../components/ui'
import { AccessButton, BackendOffline } from '../components/AdminGate'
import { useAccess } from '../lib/access'
import { api } from '../lib/api'
import { formatBytes, formatDateTime, formatDuration, formatPercent, STATUS_LABELS, timeAgo } from '../lib/format'
import { usePolling } from '../lib/usePolling'

const POLL_SECONDS = 15
const RANGES = [['1h', '1 hour'], ['6h', '6 hours'], ['24h', '24 hours'], ['7d', '7 days']]
const METRICS = [['cpu', 'CPU'], ['memory', 'Memory'], ['disk', 'Disk']]

const STATUS_DETAIL = {
  healthy: 'All checks within limits',
  warning: 'A metric is at or above its limit',
  offline: 'The agent has stopped reporting',
  unknown: 'The agent has not reported yet',
  disabled: 'Reports from this server are refused',
}

function StatusTile({ server }) {
  return (
    <section className={`tile tile-status tile-status-${server.status}`} aria-label="Server status">
      <div className="tile-head">
        <h2 className="label">Status</h2>
        <StatusDot status={server.status} />
      </div>
      <p className="status-word">{STATUS_LABELS[server.status]}</p>
      <p className="tile-foot">
        <span>{STATUS_DETAIL[server.status]}</span>
        <span className="tile-foot-time">{timeAgo(server.last_seen_at)}</span>
      </p>
    </section>
  )
}

function UsageTile({ label, percent, limit, used, total }) {
  const available = typeof percent === 'number'
  const warning = available && percent >= limit
  return (
    <section
      className={`tile ${warning ? 'tile-warning' : ''}`}
      aria-label={`${label}: ${available ? `${formatPercent(percent)} percent` : 'no data'}, limit ${limit} percent`}
    >
      <div className="tile-head">
        <h2 className="label">{label}</h2>
        {warning && <span className="tag">Over limit</span>}
      </div>
      <p className="figure" aria-hidden="true">
        {available ? (
          <>
            <span className="figure-num num-update" key={percent}>{formatPercent(percent)}</span>
            <span className="figure-unit">%</span>
          </>
        ) : (
          <span className="figure-missing">No data</span>
        )}
      </p>
      <Meter value={available ? percent : null} threshold={limit} warning={warning} />
      <p className="tile-foot" aria-hidden="true">
        <span>{total != null ? `${formatBytes(used)} of ${formatBytes(total)}` : 'Utilisation'}</span>
        <span>Limit {limit}%</span>
      </p>
    </section>
  )
}

function HistoryCard({ serverId, thresholds }) {
  const [range, setRange] = useState('1h')
  const [metric, setMetric] = useState('cpu')
  return (
    <section className="card" aria-labelledby="history-title">
      <div className="card-head card-head-wrap">
        <div>
          <h2 id="history-title" className="card-title">History</h2>
          <p className="card-sub">Stored samples from the agent</p>
        </div>
        <div className="card-tools">
          <Segmented options={METRICS} value={metric} onChange={setMetric} label="Metric" />
          <Segmented options={RANGES.map(([k]) => [k, k])} value={range} onChange={setRange} label="Time range" />
        </div>
      </div>
      <HistoryChart key={range} serverId={serverId} range={range} metric={metric} threshold={thresholds[metric]} />
    </section>
  )
}

function HistoryChart({ serverId, range, metric, threshold }) {
  const { data, error } = usePolling(() => api(`/api/servers/${serverId}/metrics?range=${range}`), 30)
  if (error) return <p className="field-error">{error.message}</p>
  if (!data) return <div className="chart-empty">Loading history…</div>
  // Break the line where the gap is clearly longer than a normal report interval
  const gap = Math.max((data.bucket_seconds ?? 30) * 3, 120)
  return (
    <>
      <LineChart
        points={data.points}
        field={metric}
        threshold={threshold}
        start={data.start}
        end={data.end}
        gapSeconds={gap}
        label={`${metric} usage over ${range}`}
      />
      <p className="muted small chart-note">
        {data.raw_samples} sample{data.raw_samples === 1 ? '' : 's'}
        {data.bucket_seconds ? ` · averaged into ${Math.round(data.bucket_seconds / 60)}-minute buckets` : ''}
      </p>
    </>
  )
}

function AgentCard({ server }) {
  const rows = [
    ['Hostname', server.hostname ?? '—'],
    ['Operating system', server.os_name ? `${server.os_name} ${server.os_version ?? ''}` : '—'],
    ['Kernel', server.kernel ?? '—'],
    ['Agent version', server.agent_version ?? '—'],
    ['Uptime', formatDuration(server.uptime_seconds)],
    ['Last report', server.last_seen_at ? `${formatDateTime(server.last_seen_at)} (${timeAgo(server.last_seen_at)})` : 'never'],
    ['First report', server.first_seen_at ? formatDateTime(server.first_seen_at) : 'never'],
    ['Failed deliveries', String(server.failed_deliveries)],
  ]
  return (
    <section className="card" aria-labelledby="agent-title">
      <div className="card-head">
        <div>
          <h2 id="agent-title" className="card-title">Agent connection</h2>
          <p className="card-sub">As last reported by the agent</p>
        </div>
      </div>
      <dl className="kv kv-compact">
        {rows.map(([k, v]) => (
          <div key={k} className="kv-row">
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      {server.last_agent_error && (
        <p className="field-error small">Last delivery error: {server.last_agent_error}</p>
      )}
    </section>
  )
}

function ThresholdForm({ server, onSaved }) {
  const overrides = server.threshold_overrides
  const [values, setValues] = useState({
    cpu: overrides.cpu ?? '',
    memory: overrides.memory ?? '',
    disk: overrides.disk ?? '',
  })
  const [state, setState] = useState(null)

  const save = async (event) => {
    event.preventDefault()
    setState('saving')
    const body = {}
    for (const key of ['cpu', 'memory', 'disk']) body[key] = values[key] === '' ? null : Number(values[key])
    try {
      await api(`/api/servers/${server.id}`, { method: 'PATCH', body: { thresholds: body } })
      setState('saved')
      onSaved()
    } catch (err) {
      setState(err.message)
    }
  }

  return (
    <form onSubmit={save} className="threshold-form">
      {['cpu', 'memory', 'disk'].map((key) => (
        <label key={key} className="field">
          <span className="field-label">{key === 'cpu' ? 'CPU' : key[0].toUpperCase() + key.slice(1)} limit %</span>
          <input
            type="number"
            min="1"
            max="100"
            step="1"
            inputMode="numeric"
            placeholder={`default ${server.thresholds[key]}`}
            value={values[key]}
            onChange={(e) => setValues({ ...values, [key]: e.target.value })}
          />
        </label>
      ))}
      <div className="form-actions">
        <button type="submit" className="btn btn-primary" disabled={state === 'saving'}>
          Save limits
        </button>
        {state === 'saved' && <span className="muted small">Saved</span>}
        {state && !['saving', 'saved'].includes(state) && <span className="field-error small">{state}</span>}
      </div>
    </form>
  )
}

function TokensPanel({ serverId }) {
  const { data: tokens, refresh } = usePolling(() => api(`/api/servers/${serverId}/tokens`), 60)
  const [issued, setIssued] = useState(null)
  const [error, setError] = useState(null)

  const run = async (path, confirmText) => {
    if (confirmText && !window.confirm(confirmText)) return
    setError(null)
    try {
      const result = await api(path, { method: 'POST' })
      if (result?.token) setIssued(result)
      refresh()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <div className="tokens">
      {issued && (
        <div className="token-issued">
          <p className="small">
            New token <span className="mono">{issued.token_id}</span>. Copy it now; it will not be shown again. Update{' '}
            <code className="inline-code">SENTINELEYE_TOKEN</code> in <code className="inline-code">/etc/sentineleye-agent/agent.env</code>{' '}
            and restart the agent.
          </p>
          <CopyField value={issued.token} label="New agent token" />
        </div>
      )}
      {error && <p className="field-error small">{error}</p>}
      <div className="table-wrap table-wrap-flush">
        <table className="log">
          <thead>
            <tr>
              <th scope="col">Token id</th>
              <th scope="col">Created</th>
              <th scope="col">Last used</th>
              <th scope="col">State</th>
              <th scope="col" className="num-col"><span className="visually-hidden">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {(tokens ?? []).map((t) => (
              <tr key={t.token_id}>
                <td className="mono">{t.token_id}</td>
                <td className="mono">{formatDateTime(t.created_at)}</td>
                <td className="mono">{t.last_used_at ? timeAgo(t.last_used_at) : 'never'}</td>
                <td>{t.revoked_at ? <span className="muted">Revoked</span> : 'Active'}</td>
                <td className="num-col">
                  {!t.revoked_at && (
                    <button
                      type="button"
                      className="btn btn-quiet"
                      onClick={() => run(`/api/servers/${serverId}/tokens/${t.token_id}/revoke`, `Revoke token ${t.token_id}? The agent using it will be rejected.`)}
                    >
                      Revoke
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="form-actions">
        <button
          type="button"
          className="btn btn-quiet"
          onClick={() => run(`/api/servers/${serverId}/tokens/reissue`, 'Revoke every active token and issue one replacement?')}
        >
          Reissue token
        </button>
      </div>
    </div>
  )
}

function ManageCard({ server, onChanged }) {
  const [error, setError] = useState(null)

  const toggle = async () => {
    setError(null)
    try {
      await api(`/api/servers/${server.id}`, { method: 'PATCH', body: { enabled: !server.enabled } })
      onChanged()
    } catch (err) {
      setError(err.message)
    }
  }

  const remove = async () => {
    const typed = window.prompt(`This deletes ${server.name} with all of its history and alerts. Type the server name to confirm.`)
    if (typed !== server.name) return
    try {
      await api(`/api/servers/${server.id}`, { method: 'DELETE' })
      window.location.hash = '#/'
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <section className="card" aria-labelledby="manage-title">
      <div className="card-head">
        <div>
          <h2 id="manage-title" className="card-title">Settings</h2>
          <p className="card-sub">Leave a limit empty to use the global default</p>
        </div>
      </div>
      <ThresholdForm key={JSON.stringify(server.threshold_overrides)} server={server} onSaved={onChanged} />
      <h3 className="subhead">Agent tokens</h3>
      <TokensPanel serverId={server.id} />
      <h3 className="subhead">Server</h3>
      {error && <p className="field-error small">{error}</p>}
      <div className="form-actions">
        <button type="button" className="btn btn-quiet" onClick={toggle}>
          {server.enabled ? 'Disable monitoring' : 'Enable monitoring'}
        </button>
        <button type="button" className="btn btn-danger" onClick={remove}>
          Delete server
        </button>
      </div>
    </section>
  )
}

export default function ServerDetail({ id }) {
  const { isAdmin } = useAccess()
  const { data, error, loading, refresh } = usePolling(async () => {
    const [server, alerts] = await Promise.all([
      api(`/api/servers/${id}`),
      api(`/api/alerts?server_id=${id}&limit=20`),
    ])
    return { server, alerts }
  }, POLL_SECONDS)

  const server = data?.server
  const latest = server?.latest

  if (error?.status === 0) return <BackendOffline title={server?.name ?? 'Server'} onRetry={refresh} loading={loading} />

  return (
    <>
      <TopbarControls>
        {server && <StatusChip status={server.status} />}
        <RefreshButton onClick={refresh} loading={loading} label="Refresh" />
      </TopbarControls>

      <main className="page">
        <div className="page-head page-head-split">
          <div>
            <a className="back-link" href="#/">← Infrastructure</a>
            <h1>{server?.name ?? 'Server'}</h1>
            {server && (
              <p className="page-sub">
                {[server.hostname, server.environment, server.description].filter(Boolean).join(' · ') || 'Waiting for the agent'}
              </p>
            )}
          </div>
          <AccessButton />
        </div>

        <ErrorNote error={error} onRetry={refresh} />

        {server && (
          <>
            <div className={`tiles ${error ? 'stale' : ''}`}>
              <StatusTile server={server} />
              <UsageTile label="CPU" percent={latest?.cpu_percent} limit={server.thresholds.cpu} />
              <UsageTile
                label="Memory"
                percent={latest?.memory_percent}
                limit={server.thresholds.memory}
                used={latest?.memory_used_bytes}
                total={latest?.memory_total_bytes}
              />
              <UsageTile
                label="Disk"
                percent={latest?.disk_percent}
                limit={server.thresholds.disk}
                used={latest?.disk_used_bytes}
                total={latest?.disk_total_bytes}
              />
            </div>

            <div className="split">
              <HistoryCard serverId={server.id} thresholds={server.thresholds} />
              <AgentCard server={server} />
            </div>

            <section className="card" aria-labelledby="server-alerts-title">
              <div className="card-head">
                <div>
                  <h2 id="server-alerts-title" className="card-title">Alerts</h2>
                  <p className="card-sub">Latest 20 for this server</p>
                </div>
              </div>
              <AlertTable alerts={data.alerts} onChanged={refresh} showServer={false} />
            </section>

            {isAdmin && <ManageCard server={server} onChanged={refresh} />}
          </>
        )}
      </main>
    </>
  )
}
