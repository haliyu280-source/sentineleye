import { useEffect, useState } from 'react'

// Hash routes keep the dashboard a static bundle: no server-side routing needed.
//   #/            fleet overview
//   #/servers/3   one server
//   #/alerts      alert centre
//   #/local       this host (the original health page)

function parse(hash) {
  const path = hash.replace(/^#/, '') || '/'
  const server = path.match(/^\/servers\/(\d+)$/)
  if (server) return { page: 'server', id: Number(server[1]) }
  if (path === '/alerts') return { page: 'alerts' }
  if (path === '/local') return { page: 'local' }
  return { page: 'fleet' }
}

export function useRoute() {
  const [route, setRoute] = useState(() => parse(window.location.hash))
  useEffect(() => {
    const onChange = () => {
      setRoute(parse(window.location.hash))
      window.scrollTo(0, 0)
    }
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}
