import { useState } from 'react'
import { useHealth, REFRESH_SECONDS, HISTORY_LIMIT } from './useHealth'
import './App.css'

const STATUS_LABELS = {
  healthy: 'Healthy',
  warning: 'Warning',
  offline: 'Offline',
}

const OS_NAMES = { Darwin: 'macOS', Linux: 'Linux' }

const formatPercent = (value) => (Number.isInteger(value) ? String(value) : value.toFixed(1))
const formatTime = (date) =>
  date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
const formatMs = (ms) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`)

// Turns one check from the API into a short tag and a sentence that says what is wrong.
// `check` and `threshold` are undefined when the backend predates per-check fields.
function describeCheck({ name, setting, value, check, threshold }) {
  if (check !== 'warning') return { state: check, tag: null, sentence: null }

  if (threshold === null) {
    return {
      state: 'warning',
      tag: 'Invalid limit',
      sentence: `The ${name} limit isn't valid. Set ${setting} to a whole number from 0 to 100.`,
    }
  }
  if (typeof value !== 'number') {
    return { state: 'warning', tag: 'Unreadable', sentence: `${name} usage couldn't be read on this server.` }
  }
  if (typeof threshold === 'number' && value >= threshold) {
    return {
      state: 'warning',
      tag: 'Over limit',
      sentence: `${name} is at ${formatPercent(value)}%, at or above the ${threshold}% limit.`,
    }
  }
  return { state: 'warning', tag: 'Check failed', sentence: `The ${name} check didn't complete.` }
}

function StatusDot({ status }) {
  return <span className={`dot dot-${status}`} aria-hidden="true" />
}

function Meter({ value, threshold, warning }) {
  const fill = Math.min(Math.max(value ?? 0, 0), 100)
  return (
    <div className={`meter ${warning ? 'meter-warning' : ''}`} aria-hidden="true">
      {typeof value === 'number' && <span className="meter-fill" style={{ width: `${fill}%` }} />}
      {typeof threshold === 'number' && (
        <span className="meter-limit" style={{ left: `${Math.min(Math.max(threshold, 0), 100)}%` }} />
      )}
    </div>
  )
}

function StatusTile({ status, disk, cpu, checkedAt, error }) {
  const checks = [disk, cpu].filter((c) => c?.state)
  const failing = checks.filter((c) => c.state === 'warning').length
  let detail = 'Waiting for the first reading'
  if (status === 'offline') detail = error?.kind === 'unreachable' ? 'Backend not reachable' : 'Health check failed'
  else if (checks.length && failing === 0) detail = `All ${checks.length} checks passing`
  else if (checks.length) detail = `${failing} of ${checks.length} checks need attention`
  else if (status === 'warning') detail = 'A check needs attention'

  return (
    <section className={`tile tile-status tile-status-${status ?? 'pending'}`} aria-label="System status">
      <div className="tile-head">
        <h2 className="label">System status</h2>
        {status && <StatusDot status={status} />}
      </div>
      <p className="status-word">{status ? STATUS_LABELS[status] : '—'}</p>
      <p className="tile-foot">
        <span>{detail}</span>
        <span className="tile-foot-time">{checkedAt ? formatTime(checkedAt) : '—'}</span>
      </p>
    </section>
  )
}

function MetricTile({ label, value, caption, threshold, info }) {
  const available = typeof value === 'number'
  const warning = info.state === 'warning'
  const limitText = typeof threshold === 'number' ? `Limit ${threshold}%` : null
  const spoken = [
    `${label}: ${available ? `${formatPercent(value)} percent` : 'unavailable'}`,
    limitText,
    info.tag,
  ].filter(Boolean).join(', ')

  return (
    <section className={`tile ${warning ? 'tile-warning' : ''}`} aria-label={spoken}>
      <div className="tile-head">
        <h2 className="label">{label}</h2>
        {info.tag && <span className="tag">{info.tag}</span>}
      </div>
      <p className="figure" aria-hidden="true">
        {available ? (
          <>
            {/* key on the value so the settle animation replays only when the reading changes */}
            <span className="figure-num num-update" key={value}>{formatPercent(value)}</span>
            <span className="figure-unit">%</span>
          </>
        ) : (
          <span className="figure-missing">Unavailable</span>
        )}
      </p>
      <Meter value={available ? value : null} threshold={threshold} warning={warning} />
      <p className="tile-foot" aria-hidden="true">
        <span>{caption}</span>
        {limitText && <span>{limitText}</span>}
      </p>
    </section>
  )
}

function MemoryTile({ totalMb, os }) {
  const available = typeof totalMb === 'number'
  return (
    <section className="tile" aria-label="Memory">
      <div className="tile-head">
        <h2 className="label">Memory</h2>
      </div>
      <p className="figure">
        {available ? (
          <>
            <span className="figure-num">{(totalMb / 1024).toFixed(totalMb % 1024 === 0 ? 0 : 1)}</span>
            <span className="figure-unit">GB</span>
          </>
        ) : (
          <span className="figure-missing">Unavailable</span>
        )}
      </p>
      <p className="tile-foot">
        <span>{available ? `${totalMb.toLocaleString()} MB physical` : 'Total physical memory'}</span>
        <span>{OS_NAMES[os] ?? os ?? '—'}</span>
      </p>
    </section>
  )
}

function TrendChart({ history, metric, threshold }) {
  const readings = history.slice(-HISTORY_LIMIT)
  const key = metric === 'cpu' ? 'cpu' : 'disk'
  const statusKey = metric === 'cpu' ? 'cpuStatus' : 'diskStatus'
  const width = 600
  const height = 180
  const slot = width / HISTORY_LIMIT
  const barW = Math.max(slot * 0.56, 2)
  const y = (v) => height - (Math.min(Math.max(v, 0), 100) / 100) * height

  if (readings.length < 2) {
    return (
      <div className="chart-empty">
        Collecting readings. The trend fills in as new checks arrive every {REFRESH_SECONDS}s.
      </div>
    )
  }

  return (
    <div className="chart">
      <div className="chart-axis" aria-hidden="true">
        <span>100%</span>
        <span>50%</span>
        <span>0%</span>
      </div>
      <svg
        className="chart-plot"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`${metric === 'cpu' ? 'CPU' : 'Disk'} usage over the last ${readings.length} checks`}
      >
        <line className="chart-grid" x1="0" x2={width} y1={y(50)} y2={y(50)} />
        <line className="chart-grid" x1="0" x2={width} y1={height - 0.5} y2={height - 0.5} />
        {readings.map((r, i) => {
          // Right-align so the newest reading always sits at the right edge
          const x = (HISTORY_LIMIT - readings.length + i) * slot + (slot - barW) / 2
          if (typeof r[key] !== 'number') {
            return <rect key={r.at.getTime()} className="bar-gap" x={x} y={height - 3} width={barW} height={3} />
          }
          return (
            <rect
              key={r.at.getTime()}
              className={`bar ${r[statusKey] === 'warning' ? 'bar-warning' : ''}`}
              x={x}
              y={y(r[key])}
              width={barW}
              height={height - y(r[key])}
            >
              <title>{`${formatTime(r.at)} · ${formatPercent(r[key])}%`}</title>
            </rect>
          )
        })}
        {typeof threshold === 'number' && (
          <line className="chart-limit" x1="0" x2={width} y1={y(threshold)} y2={y(threshold)} />
        )}
      </svg>
      <div className="chart-foot" aria-hidden="true">
        <span>{formatTime(readings[0].at)}</span>
        {typeof threshold === 'number' && (
          <span className="chart-key">
            <span className="chart-key-line" /> Limit {threshold}%
          </span>
        )}
        <span>{formatTime(readings[readings.length - 1].at)}</span>
      </div>
    </div>
  )
}

function ChecksList({ data, disk, cpu, error, history }) {
  const timed = history.filter((r) => typeof r.ms === 'number')
  const avgMs = timed.length ? timed.reduce((s, r) => s + r.ms, 0) / timed.length : null

  const rows = [
    {
      name: 'Disk usage',
      value: typeof data?.disk_usage === 'number' ? `${formatPercent(data.disk_usage)}%` : '—',
      limit: typeof data?.disk_threshold === 'number' ? `/ ${data.disk_threshold}%` : '',
      status: error ? 'offline' : disk?.state ?? data?.status ?? null,
      note: disk?.tag,
    },
    {
      name: 'CPU usage',
      value: typeof data?.cpu_usage === 'number' ? `${formatPercent(data.cpu_usage)}%` : '—',
      limit: typeof data?.cpu_threshold === 'number' ? `/ ${data.cpu_threshold}%` : '',
      status: error ? 'offline' : cpu?.state ?? data?.status ?? null,
      note: cpu?.tag,
    },
    {
      name: 'Backend',
      value: avgMs != null ? formatMs(avgMs) : '—',
      limit: avgMs != null ? 'avg' : '',
      status: error ? 'offline' : data ? 'healthy' : null,
      note: error ? (error.kind === 'unreachable' ? 'Unreachable' : 'Check failed') : null,
    },
  ]

  return (
    <ul className="checks">
      {rows.map((row) => (
        <li key={row.name} className="check">
          <span className="check-name">{row.name}</span>
          <span className="check-value">
            {row.value} <span className="check-limit">{row.limit}</span>
          </span>
          <span className={`check-status check-status-${row.status ?? 'pending'}`}>
            {row.status && <StatusDot status={row.status} />}
            {row.note ?? (row.status ? STATUS_LABELS[row.status] : 'Pending')}
          </span>
        </li>
      ))}
    </ul>
  )
}

function CheckLog({ history }) {
  const rows = [...history].reverse().slice(0, 8)
  if (rows.length === 0) {
    return <p className="log-empty">No checks yet this session.</p>
  }
  return (
    <div className="table-wrap">
      <table className="log">
        <thead>
          <tr>
            <th scope="col">Time</th>
            <th scope="col">Status</th>
            <th scope="col" className="num-col">Disk</th>
            <th scope="col" className="num-col">CPU</th>
            <th scope="col" className="num-col">Response</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.at.getTime()}>
              <td className="mono">{formatTime(r.at)}</td>
              <td>
                <span className="log-status">
                  <StatusDot status={r.status === 'healthy' ? 'healthy' : r.status === 'offline' ? 'offline' : 'warning'} />
                  {STATUS_LABELS[r.status] ?? 'Warning'}
                </span>
              </td>
              <td className="num-col mono">{typeof r.disk === 'number' ? `${formatPercent(r.disk)}%` : '—'}</td>
              <td className="num-col mono">{typeof r.cpu === 'number' ? `${formatPercent(r.cpu)}%` : '—'}</td>
              <td className="num-col mono">{formatMs(r.ms)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ErrorAlert({ error, hasData }) {
  const fallback = hasData ? 'Showing the last good reading.' : `Retrying every ${REFRESH_SECONDS}s.`

  if (error.kind === 'unreachable') {
    return (
      <div className="alert" role="alert">
        <strong>Can't reach the SentinelEye backend.</strong> {error.message}. Start it from the
        project folder with <code>python -m fastapi dev main.py</code>. {fallback}
      </div>
    )
  }
  return (
    <div className="alert" role="alert">
      <strong>The health check failed.</strong> {error.message}. The backend terminal has the
      details. {fallback}
    </div>
  )
}

function WarningAlert({ sentences }) {
  return (
    <div className="alert alert-warning" role="alert">
      <strong>Attention needed.</strong>{' '}
      {sentences.length > 0
        ? sentences.join(' ')
        : 'A disk or CPU check reported a problem on this server.'}
    </div>
  )
}

function SkeletonTiles() {
  return [0, 1, 2, 3].map((i) => (
    <section className="tile skeleton" key={i} aria-hidden="true">
      <div className="sk sk-label" />
      <div className="sk sk-figure" />
      <div className="sk sk-meter" />
    </section>
  ))
}

export default function App() {
  const { data, error, checkedAt, loading, secondsLeft, refresh, history } = useHealth()
  const [metric, setMetric] = useState('cpu')
  const status = error ? 'offline' : data?.status === 'healthy' ? 'healthy' : data ? 'warning' : null
  const stale = Boolean(error && data)

  const disk = data
    ? describeCheck({
        name: 'Disk',
        setting: 'DISK_THRESHOLD',
        value: data.disk_usage,
        check: data.disk_status,
        threshold: data.disk_threshold,
      })
    : null
  const cpu = data
    ? describeCheck({
        name: 'CPU',
        setting: 'CPU_THRESHOLD',
        value: data.cpu_usage,
        check: data.cpu_status,
        threshold: data.cpu_threshold,
      })
    : null

  return (
    <div className="shell">
      <header className="topbar">
        <div className="topbar-inner">
          <a className="brand" href="/" aria-label="SentinelEye home">
            <img className="brand-mark" src="/sentinel-mark.png" alt="" width="24" height="27" />
            <span className="brand-name">SentinelEye</span>
          </a>

          <div className="controls">
            {status && (
              <span className={`chip chip-${status}`} role="status">
                <StatusDot status={status} />
                <span className="chip-text">{STATUS_LABELS[status]}</span>
              </span>
            )}
            <button
              type="button"
              className="refresh"
              onClick={refresh}
              disabled={loading}
              aria-label="Refresh now"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true" className={loading ? 'spin' : ''}>
                <path d="M20 12a8 8 0 1 1-2.34-5.66M20 4v4h-4" />
              </svg>
              <span className="countdown" aria-live="off">
                {loading ? 'Checking' : `${secondsLeft}s`}
              </span>
            </button>
          </div>
        </div>
      </header>

      <main className="page">
        <div className="page-head">
          <h1>System overview</h1>
          <p className="page-sub">A sharper eye on your infrastructure.</p>
        </div>

        {error && <ErrorAlert error={error} hasData={Boolean(data)} />}
        {status === 'warning' && (
          <WarningAlert sentences={[disk, cpu].map((c) => c.sentence).filter(Boolean)} />
        )}

        <div className={`tiles ${stale ? 'stale' : ''}`}>
          {data ? (
            <>
              <StatusTile status={status} disk={disk} cpu={cpu} checkedAt={checkedAt} error={error} />
              <MetricTile
                label="Disk"
                value={data.disk_usage}
                caption="Root filesystem used"
                threshold={data.disk_threshold}
                info={disk}
              />
              <MetricTile
                label="CPU"
                value={data.cpu_usage}
                caption="Current utilisation"
                threshold={data.cpu_threshold}
                info={cpu}
              />
              <MemoryTile totalMb={data.memory_total_mb} os={data.operating_system} />
            </>
          ) : error ? (
            <StatusTile status={status} checkedAt={null} error={error} />
          ) : (
            <SkeletonTiles />
          )}
        </div>

        <div className="split">
          <section className="card" aria-labelledby="trend-title">
            <div className="card-head">
              <div>
                <h2 id="trend-title" className="card-title">Trend</h2>
                <p className="card-sub">Last {HISTORY_LIMIT} checks · this session</p>
              </div>
              <div className="segmented" role="group" aria-label="Metric">
                {['cpu', 'disk'].map((m) => (
                  <button
                    key={m}
                    type="button"
                    aria-pressed={metric === m}
                    onClick={() => setMetric(m)}
                  >
                    {m === 'cpu' ? 'CPU' : 'Disk'}
                  </button>
                ))}
              </div>
            </div>
            <TrendChart
              history={history}
              metric={metric}
              threshold={metric === 'cpu' ? data?.cpu_threshold : data?.disk_threshold}
            />
          </section>

          <section className="card" aria-labelledby="checks-title">
            <div className="card-head">
              <div>
                <h2 id="checks-title" className="card-title">Checks</h2>
                <p className="card-sub">Every {REFRESH_SECONDS}s from /api/health</p>
              </div>
            </div>
            <ChecksList data={data} disk={disk} cpu={cpu} error={error} history={history} />
          </section>
        </div>

        <section className="card" aria-labelledby="log-title">
          <div className="card-head">
            <div>
              <h2 id="log-title" className="card-title">Check log</h2>
              <p className="card-sub">Most recent first</p>
            </div>
          </div>
          <CheckLog history={history} />
        </section>
      </main>
    </div>
  )
}
