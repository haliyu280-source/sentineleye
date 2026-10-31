import { useState } from 'react'
import { ActivityList, AlertTable } from '../components/AlertTable'
import { ErrorNote, RefreshButton, Segmented, StatusChip, TopbarControls } from '../components/ui'
import { AccessButton, BackendOffline } from '../components/AdminGate'
import { api } from '../lib/api'
import { usePolling } from '../lib/usePolling'

const FILTERS = [
  ['active', 'Active'],
  ['resolved', 'Resolved'],
  ['all', 'All'],
]

function AlertList({ filter }) {
  const { data, error, refresh } = usePolling(() => api(`/api/alerts?status=${filter}&limit=200`), 15)
  if (error) return <ErrorNote error={error} onRetry={refresh} />
  if (!data) return <p className="log-empty">Loading…</p>
  return <AlertTable alerts={data} onChanged={refresh} />
}

export default function Alerts() {
  const [filter, setFilter] = useState('active')
  const { data, error, loading, refresh } = usePolling(async () => {
    const [overview, activity] = await Promise.all([api('/api/overview'), api('/api/alert-events?limit=20')])
    return { overview, activity }
  }, 15)

  const active = data ? data.overview.alerts.open + data.overview.alerts.acknowledged : null

  if (error?.status === 0) return <BackendOffline title="Alerts" onRetry={refresh} loading={loading} />

  return (
    <>
      <TopbarControls>
        {active != null && (
          <StatusChip status={active ? 'warning' : 'healthy'} label={active ? `${active} active` : 'No alerts'} />
        )}
        <RefreshButton onClick={refresh} loading={loading} label="Refresh" />
      </TopbarControls>

      <main className="page">
        <div className="page-head page-head-split">
          <div>
            <h1>Alerts</h1>
            <p className="page-sub">
              One incident per server and condition. Recoveries close incidents automatically.
            </p>
          </div>
          <AccessButton />
        </div>

        <ErrorNote error={error} onRetry={refresh} />

        <section className="card" aria-labelledby="alerts-title">
          <div className="card-head">
            <div>
              <h2 id="alerts-title" className="card-title">Incidents</h2>
              <p className="card-sub">
                {data
                  ? `${data.overview.alerts.open} open · ${data.overview.alerts.acknowledged} acknowledged`
                  : 'Loading…'}
              </p>
            </div>
            <Segmented options={FILTERS} value={filter} onChange={setFilter} label="Filter" />
          </div>
          <AlertList key={filter} filter={filter} />
        </section>

        <section className="card" aria-labelledby="history-title">
          <div className="card-head">
            <div>
              <h2 id="history-title" className="card-title">History</h2>
              <p className="card-sub">Openings, acknowledgements, recoveries and resolutions</p>
            </div>
          </div>
          <ActivityList events={data?.activity} />
        </section>
      </main>
    </>
  )
}
