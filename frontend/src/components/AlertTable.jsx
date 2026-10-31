import { Fragment, useEffect, useState } from 'react'
import { useAccess } from '../lib/access'
import { api } from '../lib/api'
import { formatDateTime, formatPercent, KIND_LABELS, timeAgo } from '../lib/format'
import { StatusText } from './ui'

const ALERT_STATUS = { open: 'warning', acknowledged: 'pending', resolved: 'healthy' }

function Timeline({ alertId }) {
  const [state, setState] = useState({})

  useEffect(() => {
    let cancelled = false
    api(`/api/alerts/${alertId}`)
      .then((detail) => !cancelled && setState({ detail }))
      .catch((error) => !cancelled && setState({ error }))
    return () => {
      cancelled = true
    }
  }, [alertId])

  if (state.error) return <p className="muted">Could not load history: {state.error.message}</p>
  if (!state.detail) return <p className="muted">Loading history…</p>
  return (
    <ol className="timeline">
      {state.detail.events.map((e) => (
        <li key={e.id}>
          <span className="timeline-time mono">{formatDateTime(e.at)}</span>
          <span className="timeline-event">{e.event}</span>
          <span className="timeline-actor">{e.actor}</span>
          {e.detail && <span className="timeline-detail">{e.detail}</span>}
        </li>
      ))}
    </ol>
  )
}

export function AlertTable({ alerts, onChanged, showServer = true }) {
  const { isAdmin } = useAccess()
  const [busy, setBusy] = useState(null)
  const [expanded, setExpanded] = useState(null)
  const [error, setError] = useState(null)

  const act = async (alert, action) => {
    setBusy(alert.id)
    setError(null)
    try {
      await api(`/api/alerts/${alert.id}/${action}`, { method: 'POST', body: {} })
      onChanged?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(null)
    }
  }

  if (alerts.length === 0) return <p className="log-empty">No alerts match this view.</p>

  return (
    <>
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      <div className="table-wrap">
        <table className="log">
          <thead>
            <tr>
              <th scope="col">Alert</th>
              {showServer && <th scope="col">Server</th>}
              <th scope="col">Status</th>
              <th scope="col" className="num-col">Value / limit</th>
              <th scope="col">Opened</th>
              <th scope="col">Last seen</th>
              {isAdmin && (
                <th scope="col" className="num-col">
                  <span className="visually-hidden">Actions</span>
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {alerts.map((a) => (
              <Fragment key={a.id}>
                <tr className={a.severity === 'critical' && a.status !== 'resolved' ? 'row-critical' : undefined}>
                  <td>
                    <button
                      type="button"
                      className="row-toggle"
                      aria-expanded={expanded === a.id}
                      onClick={() => setExpanded(expanded === a.id ? null : a.id)}
                    >
                      {KIND_LABELS[a.kind] ?? a.kind}
                    </button>
                  </td>
                  {showServer && (
                    <td>
                      <a className="table-link" href={`#/servers/${a.server_id}`}>
                        {a.server_name}
                      </a>
                    </td>
                  )}
                  <td>
                    <StatusText status={ALERT_STATUS[a.status]}>
                      {a.status === 'resolved' && a.resolution === 'recovered' ? 'Recovered' : a.status[0].toUpperCase() + a.status.slice(1)}
                    </StatusText>
                  </td>
                  <td className="num-col mono">
                    {a.last_value != null ? `${formatPercent(a.last_value)}%` : '—'}
                    {a.threshold != null && <span className="muted"> / {a.threshold}%</span>}
                  </td>
                  <td className="mono">{formatDateTime(a.opened_at)}</td>
                  <td className="mono">{a.status === 'resolved' ? formatDateTime(a.resolved_at) : timeAgo(a.last_observed_at)}</td>
                  {isAdmin && (
                    <td className="num-col">
                      <span className="row-actions">
                        {a.status === 'open' && (
                          <button type="button" className="btn btn-quiet" disabled={busy === a.id} onClick={() => act(a, 'acknowledge')}>
                            Acknowledge
                          </button>
                      )}
                      {a.status !== 'resolved' && (
                        <button type="button" className="btn btn-quiet" disabled={busy === a.id} onClick={() => act(a, 'resolve')}>
                          Resolve
                        </button>
                      )}
                    </span>
                  </td>
                  )}
                </tr>
                {expanded === a.id && (
                  <tr className="row-detail">
                    <td colSpan={(showServer ? 6 : 5) + (isAdmin ? 1 : 0)}>
                      <p className="row-detail-message">{a.message}</p>
                      <Timeline alertId={a.id} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

export function ActivityList({ events }) {
  if (!events?.length) return <p className="log-empty">No alert activity yet.</p>
  const tone = { opened: 'warning', recovered: 'healthy', resolved: 'healthy', acknowledged: 'pending' }
  return (
    <ul className="checks">
      {events.map((e) => (
        <li key={e.id} className="check">
          <span className="check-name">
            <a className="table-link" href={`#/servers/${e.server_id}`}>
              {e.server_name}
            </a>{' '}
            · {KIND_LABELS[e.kind] ?? e.kind}
          </span>
          <span className="check-value check-value-small">{e.detail ?? e.event}</span>
          <span className={`check-status check-status-${tone[e.event] ?? 'pending'}`}>
            {e.event[0].toUpperCase() + e.event.slice(1)}
            <span className="muted mono"> {timeAgo(e.at)}</span>
          </span>
        </li>
      ))}
    </ul>
  )
}
