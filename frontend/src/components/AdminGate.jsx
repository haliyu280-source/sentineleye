import { useState } from 'react'
import { useAccess } from '../lib/access'
import { api, ApiError, setToken } from '../lib/api'
import { OfflineHint } from './ui'

export function SignInForm({ onDone }) {
  const { publicMode } = useAccess()
  const [value, setValue] = useState('')
  const [error, setError] = useState(null)
  const [checking, setChecking] = useState(false)

  const submit = async (event) => {
    event.preventDefault()
    if (!value.trim()) return
    setChecking(true)
    setError(null)
    setToken(value.trim())
    try {
      // A management-only endpoint, so public read access can't make a wrong token look valid
      await api('/api/servers/0/tokens').catch((err) => {
        if (!(err instanceof ApiError && err.status === 404)) throw err
      })
      setValue('')
      onDone?.()
    } catch (err) {
      setToken(null)
      if (err instanceof ApiError && err.status === 503) {
        setError('The management API is disabled. Set SENTINELEYE_ADMIN_TOKEN on the backend and restart it.')
      } else if (err instanceof ApiError && err.status === 401) {
        setError('That token was not accepted.')
      } else {
        setError(err.message)
      }
    } finally {
      setChecking(false)
    }
  }

  return (
    <main className="page">
      <div className="page-head">
        <h1>{publicMode ? 'Admin sign in' : 'Fleet access'}</h1>
        <p className="page-sub">
          {publicMode ? 'Signing in adds server registration, settings, tokens and alert actions. ' : ''}
          Enter the admin token configured on the backend as <code className="inline-code">SENTINELEYE_ADMIN_TOKEN</code>.
          It is kept in this browser tab only.
        </p>
      </div>
      <form className="card signin" onSubmit={submit}>
        <label className="field">
          <span className="field-label">Admin token</span>
          <input
            type="password"
            autoComplete="current-password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            aria-invalid={Boolean(error)}
            aria-describedby={error ? 'signin-error' : undefined}
            autoFocus
          />
        </label>
        {error && (
          <p id="signin-error" className="field-error" role="alert">
            {error}
          </p>
        )}
        <div className="form-actions">
          <button type="submit" className="btn btn-primary" disabled={checking || !value.trim()}>
            {checking ? 'Checking…' : 'Continue'}
          </button>
          <a className="link-button" href={publicMode ? '#/' : '#/central'}>
            {publicMode ? 'Back to the dashboard' : 'View the central server without signing in'}
          </a>
        </div>
      </form>
    </main>
  )
}

// Fleet pages: open to everyone in public mode, otherwise only after signing in.
// An unreachable backend is reported as offline rather than as a sign-in prompt.
export function AdminGate({ children }) {
  const { ready, offline, publicMode, isAdmin } = useAccess()
  if (!ready) return <main className="page" />
  if (offline) return <BackendOffline />
  if (publicMode || isAdmin) return children
  return <SignInForm />
}

function BackendOffline() {
  return (
    <main className="page">
      <div className="page-head">
        <h1>Infrastructure</h1>
        <p className="page-sub">No live data is shown while the backend is unreachable.</p>
      </div>
      <div className="alert" role="alert">
        <strong>Can't reach the SentinelEye backend.</strong> <OfflineHint /> This page checks again every
        15 seconds.
      </div>
    </main>
  )
}

export function AccessButton() {
  const { publicMode, isAdmin } = useAccess()
  if (isAdmin) {
    return (
      <button type="button" className="btn btn-quiet" onClick={() => setToken(null)}>
        Sign out
      </button>
    )
  }
  if (!publicMode) return null
  return (
    <span className="access-note">
      Read-only view
      <a className="btn btn-quiet" href="#/signin">Admin sign in</a>
    </span>
  )
}
