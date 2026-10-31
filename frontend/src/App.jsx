import { useEffect, useState } from 'react'
import './App.css'
import { AdminGate, SignInForm } from './components/AdminGate'
import { AccessContext } from './lib/access'
import { apiUrl, getToken, onTokenChange } from './lib/api'
import { useRoute } from './lib/router'
import { TopbarSlot } from './lib/topbar'
import Alerts from './pages/Alerts'
import Fleet from './pages/Fleet'
import CentralServer from './pages/CentralServer'
import ServerDetail from './pages/ServerDetail'

const NAV = [
  ['fleet', '#/', 'Fleet'],
  ['alerts', '#/alerts', 'Alerts'],
  ['central', '#/central', 'Central server'],
]

function FleetPages({ route }) {
  if (route.page === 'server') return <ServerDetail key={route.id} id={route.id} />
  if (route.page === 'alerts') return <Alerts />
  return <Fleet />
}

const META_RETRY_SECONDS = 15

// null while loading, the /api/meta response when the backend answers, 'offline' when it doesn't.
// While offline it keeps asking, so the dashboard recovers by itself when the backend returns.
function useAccessState() {
  const [meta, setMeta] = useState(null)
  const [token, setCurrentToken] = useState(getToken)

  useEffect(() => onTokenChange(setCurrentToken), [])

  useEffect(() => {
    let cancelled = false
    let timer
    const load = () =>
      fetch(apiUrl('/api/meta'), { cache: 'no-store' })
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
        .then((body) => !cancelled && setMeta(body))
        .catch(() => {
          if (cancelled) return
          setMeta('offline')
          timer = setTimeout(load, META_RETRY_SECONDS * 1000)
        })
    load()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [])

  return {
    ready: meta !== null,
    offline: meta === 'offline',
    publicMode: Boolean(meta?.public_dashboard),
    isAdmin: Boolean(token),
  }
}

export default function App() {
  const route = useRoute()
  const access = useAccessState()
  const [controls, setControls] = useState(null)
  const section = route.page === 'server' ? 'fleet' : route.page

  let page
  if (route.page === 'central') page = <CentralServer />
  else if (route.page === 'signin') page = <SignInForm onDone={() => (window.location.hash = '#/')} />
  else page = <AdminGate><FleetPages route={route} /></AdminGate>

  return (
    <AccessContext.Provider value={access}>
      <TopbarSlot.Provider value={controls}>
        <div className="shell">
          <header className="topbar">
            <div className="topbar-inner">
              <a className="brand" href="#/" aria-label="SentinelEye home">
                <img className="brand-mark" src="/sentinel-mark.png" alt="" width="24" height="27" />
                <span className="brand-name">SentinelEye</span>
              </a>

              <nav className="nav" aria-label="Sections">
                {NAV.map(([key, href, label]) => (
                  <a key={key} href={href} aria-current={section === key ? 'page' : undefined}>
                    {label}
                  </a>
                ))}
              </nav>

              <div className="controls" ref={setControls} />
            </div>
          </header>

          {page}

          <footer className="site-footer">
            <div className="site-footer-inner">
              <span>SentinelEye · A sharper eye on your infrastructure.</span>
              <span className="site-footer-credit">Created by: Ali K. Hassan · © 2026</span>
            </div>
          </footer>
        </div>
      </TopbarSlot.Provider>
    </AccessContext.Provider>
  )
}
