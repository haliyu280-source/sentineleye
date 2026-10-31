import { useEffect, useState } from 'react'
import { api, ApiError, getToken, onTokenChange, setToken } from '../lib/api'

// Fleet pages need the backend's admin token. It is checked against the API before being kept.
export function AdminGate({ children }) {
  const [token, setCurrent] = useState(getToken)
  const [value, setValue] = useState('')
  const [error, setError] = useState(null)
  const [checking, setChecking] = useState(false)

  useEffect(() => onTokenChange(setCurrent), [])

  if (token) return children

  const submit = async (event) => {
    event.preventDefault()
    if (!value.trim()) return
    setChecking(true)
    setError(null)
    setToken(value.trim())
    try {
      await api('/api/overview')
      setValue('')
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
        <h1>Fleet access</h1>
        <p className="page-sub">
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
          <a className="link-button" href="#/local">
            View this host without signing in
          </a>
        </div>
      </form>
    </main>
  )
}

export function SignOutButton() {
  return (
    <button type="button" className="btn btn-quiet" onClick={() => setToken(null)}>
      Sign out
    </button>
  )
}
