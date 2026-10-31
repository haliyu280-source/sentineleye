import { useState } from 'react'
import './App.css'
import { AdminGate } from './components/AdminGate'
import { useRoute } from './lib/router'
import { TopbarSlot } from './lib/topbar'
import Alerts from './pages/Alerts'
import Fleet from './pages/Fleet'
import LocalHost from './pages/LocalHost'
import ServerDetail from './pages/ServerDetail'

const NAV = [
  ['fleet', '#/', 'Fleet'],
  ['alerts', '#/alerts', 'Alerts'],
  ['local', '#/local', 'Local host'],
]

function FleetPages({ route }) {
  if (route.page === 'server') return <ServerDetail key={route.id} id={route.id} />
  if (route.page === 'alerts') return <Alerts />
  return <Fleet />
}

export default function App() {
  const route = useRoute()
  const [controls, setControls] = useState(null)
  const section = route.page === 'server' ? 'fleet' : route.page

  return (
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

        {route.page === 'local' ? (
          <LocalHost />
        ) : (
          <AdminGate>
            <FleetPages route={route} />
          </AdminGate>
        )}

        <footer className="site-footer">
          <div className="site-footer-inner">
            <span>SentinelEye · A sharper eye on your infrastructure.</span>
            <span className="site-footer-credit">Created by: Ali K. Hassan · © 2026</span>
          </div>
        </footer>
      </div>
    </TopbarSlot.Provider>
  )
}
