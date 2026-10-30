import { useHealth, REFRESH_SECONDS } from './useHealth'
import './App.css'

const STATUS_LABELS = {
  healthy: 'Healthy',
  warning: 'Warning',
  offline: 'Offline',
}

const formatPercent = (value) => (Number.isInteger(value) ? String(value) : value.toFixed(1))

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

function Logo() {
  return (
    <svg className="logo" viewBox="0 0 32 32" aria-hidden="true">
      <path d="M2 16C6 9 10.5 6 16 6s10 3 14 10c-4 7-8.5 10-14 10S6 23 2 16Z" />
      <circle cx="16" cy="16" r="5" />
      <circle cx="16" cy="16" r="1.8" className="logo-pupil" />
    </svg>
  )
}

function StatusBadge({ status }) {
  return (
    <span className={`badge badge-${status}`} role="status">
      <span className="badge-dot" aria-hidden="true" />
      {STATUS_LABELS[status]}
    </span>
  )
}

function Gauge({ value, threshold }) {
  const radius = 52
  const circumference = 2 * Math.PI * radius
  const sweep = 0.75
  const arc = circumference * sweep
  const clamped = Math.min(Math.max(value ?? 0, 0), 100)
  const filled = (clamped / 100) * arc

  // Limit marker: same 270° sweep the arc uses, drawn in the gauge's rotated frame
  let marker = null
  if (typeof threshold === 'number') {
    const angle = (Math.min(Math.max(threshold, 0), 100) / 100) * sweep * 2 * Math.PI
    const at = (r) => [64 + r * Math.cos(angle), 64 + r * Math.sin(angle)]
    const [x1, y1] = at(radius - 9)
    const [x2, y2] = at(radius + 9)
    marker = <line className="gauge-limit" x1={x1} y1={y1} x2={x2} y2={y2} />
  }

  return (
    <svg className="gauge" viewBox="0 0 128 128" aria-hidden="true">
      <circle
        className="gauge-track"
        cx="64" cy="64" r={radius}
        strokeDasharray={`${arc} ${circumference}`}
      />
      {value != null && (
        <circle
          className="gauge-fill"
          cx="64" cy="64" r={radius}
          strokeDasharray={`${filled} ${circumference}`}
        />
      )}
      {marker}
    </svg>
  )
}

function PercentPanel({ label, value, hint, threshold, info }) {
  const available = typeof value === 'number'
  const limitText = typeof threshold === 'number' ? `limit ${threshold}%` : null
  const spoken = [
    available ? `${formatPercent(value)} percent ${hint.toLowerCase()}` : 'Unavailable',
    limitText,
    info.tag,
  ].filter(Boolean).join(', ')

  return (
    <section className={`panel ${info.state === 'warning' ? 'panel-warning' : ''}`} aria-label={label}>
      <div className="panel-head">
        <h2 className="panel-label">{label}</h2>
        {info.tag && <span className="panel-tag">{info.tag}</span>}
      </div>
      <div className="gauge-wrap" role="img" aria-label={spoken}>
        <Gauge value={available ? value : null} threshold={threshold} />
        <div className="gauge-value" aria-hidden="true">
          {available ? (
            <>
              {/* key on the value so the settle animation replays only when the reading changes */}
              <span className="num num-update" key={value}>
                {formatPercent(value)}
              </span>
              <span className="unit">%</span>
            </>
          ) : (
            <span className="unavailable">Unavailable</span>
          )}
        </div>
      </div>
      <p className="panel-hint" aria-hidden="true">
        {hint}
        {limitText && <span className="panel-limit"> · {limitText}</span>}
      </p>
    </section>
  )
}

function MemoryPanel({ totalMb }) {
  const available = typeof totalMb === 'number'
  return (
    <section className="panel" aria-label="Memory">
      <div className="panel-head">
        <h2 className="panel-label">Memory</h2>
      </div>
      <div className="memory">
        {available ? (
          <>
            <span className="num">{(totalMb / 1024).toFixed(totalMb % 1024 === 0 ? 0 : 1)}</span>
            <span className="unit">GB</span>
          </>
        ) : (
          <span className="unavailable">Unavailable</span>
        )}
      </div>
      <p className="panel-hint">
        {available ? `${totalMb.toLocaleString()} MB total physical` : 'Total physical memory'}
      </p>
    </section>
  )
}

function SkeletonPanels() {
  return [0, 1, 2].map((i) => (
    <section className="panel skeleton" key={i} aria-hidden="true">
      <div className="sk sk-label" />
      <div className="sk sk-gauge" />
      <div className="sk sk-hint" />
    </section>
  ))
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

export default function App() {
  const { data, error, checkedAt, loading, secondsLeft, refresh } = useHealth()
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
    <div className={`app status-${status ?? 'pending'}`}>
      <header className="topbar">
        <div className="brand">
          <Logo />
          <div>
            <h1>SentinelEye</h1>
            <p className="tagline">A sharper eye on your infrastructure.</p>
          </div>
        </div>

        <div className="controls">
          {status && <StatusBadge status={status} />}
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
      </header>

      {error && <ErrorAlert error={error} hasData={Boolean(data)} />}

      {status === 'warning' && (
        <WarningAlert sentences={[disk, cpu].map((c) => c.sentence).filter(Boolean)} />
      )}

      <main className={`grid ${stale ? 'stale' : ''}`}>
        {data ? (
          <>
            <PercentPanel
              label="Disk"
              value={data.disk_usage}
              hint="Root filesystem used"
              threshold={data.disk_threshold}
              info={disk}
            />
            <PercentPanel
              label="CPU"
              value={data.cpu_usage}
              hint="Current utilisation"
              threshold={data.cpu_threshold}
              info={cpu}
            />
            <MemoryPanel totalMb={data.memory_total_mb} />
          </>
        ) : error ? (
          <p className="empty">No readings yet.</p>
        ) : (
          <SkeletonPanels />
        )}
      </main>

      <footer className="meta">
        <span>
          <span className="meta-key">OS</span> {data?.operating_system ?? '—'}
        </span>
        <span>
          <span className="meta-key">Last check</span>{' '}
          {checkedAt ? checkedAt.toLocaleTimeString() : '—'}
        </span>
        <span>
          <span className="meta-key">Refresh</span> every {REFRESH_SECONDS}s
        </span>
      </footer>
    </div>
  )
}
