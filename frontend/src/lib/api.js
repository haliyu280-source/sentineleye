// Client for the SentinelEye management API. The admin token lives in sessionStorage for
// this tab only and is sent as a Bearer token; it is cleared as soon as the API rejects it.

// Where the backend lives. Empty (the default) means the same origin: the Vite dev proxy locally,
// or FastAPI serving the dashboard itself. A separately hosted dashboard sets
// VITE_SENTINELEYE_API_URL at build time. It is a public address, never a secret.
export const API_BASE = (import.meta.env.VITE_SENTINELEYE_API_URL || '').replace(/\/+$/, '')
export const HOSTED = API_BASE !== ''
export const apiUrl = (path) => `${API_BASE}${path}`

const TOKEN_KEY = 'sentineleye.adminToken'
const listeners = new Set()

export class ApiError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
}

export function getToken() {
  try {
    return sessionStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token) {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token)
    else sessionStorage.removeItem(TOKEN_KEY)
  } catch {
    // storage unavailable (private mode): the token simply won't survive a reload
  }
  listeners.forEach((fn) => fn(token))
}

export function onTokenChange(fn) {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

function describe(body, status) {
  const detail = body?.detail
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join('; ')
  if (typeof detail === 'string') return detail
  return `Request failed (HTTP ${status})`
}

export async function api(path, { method = 'GET', body } = {}) {
  const token = getToken()
  let response
  try {
    response = await fetch(apiUrl(path), {
      method,
      cache: 'no-store',
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    throw new ApiError(0, "Can't reach the SentinelEye backend")
  }

  if (response.status === 204) return null
  const data = await response.json().catch(() => null)
  if (!response.ok) {
    if (response.status === 401) setToken(null)
    // A bare 5xx with no JSON body comes from the dev proxy when FastAPI is not running
    if (!data && response.status >= 500) throw new ApiError(0, "Can't reach the SentinelEye backend")
    throw new ApiError(response.status, describe(data, response.status))
  }
  return data
}
