import { useContext, useState } from 'react'
import { createPortal } from 'react-dom'
import { HOSTED } from '../lib/api'
import { STATUS_LABELS } from '../lib/format'
import { TopbarSlot } from '../lib/topbar'

export function StatusDot({ status }) {
  return <span className={`dot dot-${status}`} aria-hidden="true" />
}

export function StatusChip({ status, label }) {
  return (
    <span className={`chip chip-${status}`} role="status">
      <StatusDot status={status} />
      <span className="chip-text">{label ?? STATUS_LABELS[status] ?? status}</span>
    </span>
  )
}

export function StatusText({ status, children }) {
  return (
    <span className={`status-text status-text-${status}`}>
      <StatusDot status={status} />
      {children ?? STATUS_LABELS[status] ?? status}
    </span>
  )
}

export function Meter({ value, threshold, warning }) {
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

export function RefreshButton({ onClick, loading, label }) {
  return (
    <button type="button" className="refresh" onClick={onClick} disabled={loading} aria-label="Refresh now">
      <svg viewBox="0 0 24 24" aria-hidden="true" className={loading ? 'spin' : ''}>
        <path d="M20 12a8 8 0 1 1-2.34-5.66M20 4v4h-4" />
      </svg>
      <span className="countdown" aria-live="off">
        {loading ? 'Checking' : label}
      </span>
    </button>
  )
}

export function Segmented({ options, value, onChange, label }) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map(([key, text]) => (
        <button key={key} type="button" aria-pressed={value === key} onClick={() => onChange(key)}>
          {text}
        </button>
      ))}
    </div>
  )
}

// Pages put their own controls (status chip, refresh) into the shared top bar
export function TopbarControls({ children }) {
  const target = useContext(TopbarSlot)
  return target ? createPortal(children, target) : null
}

export function CopyField({ value, label }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setCopied(false)
    }
  }
  return (
    <div className="copy-field">
      <code aria-label={label}>{value}</code>
      <button type="button" className="btn btn-quiet" onClick={copy}>
        {copied ? 'Copied' : 'Copy'}
      </button>
    </div>
  )
}

// Shown whenever the backend cannot be reached. The hosted dashboard says so plainly instead of
// showing old or invented numbers; locally it tells the developer how to start the backend.
export function OfflineHint() {
  if (HOSTED) {
    return (
      <>
        The backend runs on the author's own machine and is not online all the time. Live data
        appears again as soon as it is reachable.
      </>
    )
  }
  return (
    <>
      Start it from the project folder with <code>.venv/bin/python -m uvicorn main:app --reload</code>.
    </>
  )
}

export function ErrorNote({ error, onRetry }) {
  if (!error) return null
  const unreachable = error.status === 0
  return (
    <div className="alert" role="alert">
      <strong>{unreachable ? "Can't reach the SentinelEye backend." : 'Request failed.'}</strong> {error.message}.
      {unreachable && <> <OfflineHint /></>}
      {onRetry && (
        <>
          {' '}
          <button type="button" className="link-button" onClick={onRetry}>
            Try again
          </button>
        </>
      )}
    </div>
  )
}
