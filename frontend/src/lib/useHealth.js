import { useCallback, useEffect, useRef, useState } from 'react'

export const REFRESH_SECONDS = 10

// Readings kept in memory for the trend chart and check log (this browser session only)
export const HISTORY_LIMIT = 30

const toReading = (at, body, ms) => ({
  at,
  status: body.status,
  disk: body.disk_usage,
  cpu: body.cpu_usage,
  diskStatus: body.disk_status,
  cpuStatus: body.cpu_status,
  ms,
})

class HealthError extends Error {
  constructor(kind, message) {
    super(message)
    this.kind = kind
  }
}

async function fetchHealth() {
  let response
  try {
    response = await fetch('/api/health', { cache: 'no-store' })
  } catch {
    throw new HealthError('unreachable', 'No response from the backend')
  }

  const body = await response.json().catch(() => null)
  if (!response.ok) {
    // The backend's own errors carry JSON; a bare 5xx comes from the dev proxy when FastAPI is down
    if (body?.error) throw new HealthError('failed', `${body.error} (HTTP ${response.status})`)
    throw new HealthError('unreachable', `No response from the backend (HTTP ${response.status})`)
  }
  if (!body || typeof body.status !== 'string') {
    throw new HealthError('failed', 'The backend sent a response SentinelEye could not read')
  }
  return body
}

// Polls /api/health every REFRESH_SECONDS. Keeps the last good reading when a
// request fails, and never starts a new request while one is still running.
export function useHealth() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [checkedAt, setCheckedAt] = useState(null)
  const [loading, setLoading] = useState(true)
  const [nextAt, setNextAt] = useState(null)
  const [now, setNow] = useState(() => Date.now())
  const [history, setHistory] = useState([])
  const inFlight = useRef(false)
  const timer = useRef(null)

  const refresh = useCallback(async () => {
    if (inFlight.current) return
    inFlight.current = true
    clearTimeout(timer.current)
    setLoading(true)

    const startedAt = performance.now()
    try {
      const body = await fetchHealth()
      const at = new Date()
      setData(body)
      setError(null)
      setCheckedAt(at)
      setHistory((h) => [...h, toReading(at, body, performance.now() - startedAt)].slice(-HISTORY_LIMIT))
    } catch (err) {
      setError({ kind: err.kind ?? 'failed', message: err.message })
      setHistory((h) =>
        [...h, { at: new Date(), status: 'offline', ms: performance.now() - startedAt, message: err.message }]
          .slice(-HISTORY_LIMIT),
      )
    } finally {
      inFlight.current = false
      setLoading(false)
      const finishedAt = Date.now()
      setNow(finishedAt)
      setNextAt(finishedAt + REFRESH_SECONDS * 1000)
      timer.current = setTimeout(() => refreshRef.current(), REFRESH_SECONDS * 1000)
    }
  }, [])

  const refreshRef = useRef(refresh)
  useEffect(() => {
    refreshRef.current = refresh
  }, [refresh])

  // Start polling on mount; stop on unmount
  useEffect(() => {
    const start = setTimeout(refresh, 0)
    return () => {
      clearTimeout(start)
      clearTimeout(timer.current)
    }
  }, [refresh])

  // One-second tick for the countdown display only
  useEffect(() => {
    const tick = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(tick)
  }, [])

  const secondsLeft = nextAt ? Math.max(0, Math.ceil((nextAt - now) / 1000)) : REFRESH_SECONDS

  return { data, error, checkedAt, loading, secondsLeft, refresh, history }
}
