import { useHealth, REFRESH_SECONDS } from './useHealth'
import './App.css'

const STATUS_LABELS = {
  healthy: 'Healthy',
  warning: 'Warning',
  offline: 'Offline',
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

function Gauge({ value }) {
  const radius = 52
  const circumference = 2 * Math.PI * radius
  const arc = circumference * 0.75
  const clamped = Math.min(Math.max(value ?? 0, 0), 100)
  const filled = (clamped / 100) * arc

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
    </svg>
  )
}

function PercentPanel({ label, value, hint }) {
  const available = typeof value === 'number'
  return (
    <section className="panel" aria-label={label}>
      <h2 className="panel-label">{label}</h2>
      <div className="gauge-wrap">
        <Gauge value={available ? value : null} />
        <div className="gauge-value">
          {available ? (
            <>
              {/* key on the value so the settle animation replays only when the reading changes */}
              <span className="num num-update" key={value}>
                {Number.isInteger(value) ? value : value.toFixed(1)}
              </span>
              <span className="unit">%</span>
            </>
          ) : (
            <span className="unavailable">Unavailable</span>
          )}
        </div>
      </div>
      <p className="panel-hint">{hint}</p>
    </section>
  )
}

function MemoryPanel({ totalMb }) {
  const available = typeof totalMb === 'number'
  return (
    <section className="panel" aria-label="Memory">
      <h2 className="panel-label">Memory</h2>
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

export default function App() {
  const { data, error, checkedAt, loading, secondsLeft, refresh } = useHealth()
  const status = error ? 'offline' : data?.status === 'healthy' ? 'healthy' : data ? 'warning' : null
  const stale = Boolean(error && data)

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

      {error && (
        <div className="alert" role="alert">
          <strong>Backend unavailable.</strong> {error}.
          {data ? ' Showing the last good reading.' : ` Retrying every ${REFRESH_SECONDS}s.`}
        </div>
      )}

      {status === 'warning' && (
        <div className="alert alert-warning" role="alert">
          <strong>Attention needed.</strong> A disk or CPU check reported a problem on this server.
        </div>
      )}

      <main className={`grid ${stale ? 'stale' : ''}`}>
        {data ? (
          <>
            <PercentPanel label="Disk" value={data.disk_usage} hint="Root filesystem used" />
            <PercentPanel label="CPU" value={data.cpu_usage} hint="Current utilisation" />
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
