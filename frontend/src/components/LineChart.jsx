import { formatDateTime, formatPercent } from '../lib/format'

const WIDTH = 600
const HEIGHT = 180

// Percent-over-time chart for stored history. Gaps longer than `gapSeconds` break the line,
// so periods with no data (agent offline) are visible instead of being interpolated.
export function LineChart({ points, field, threshold, start, end, gapSeconds, label }) {
  const t0 = new Date(start).getTime()
  const t1 = new Date(end).getTime()
  const x = (t) => ((new Date(t).getTime() - t0) / (t1 - t0)) * WIDTH
  const y = (v) => HEIGHT - (Math.min(Math.max(v, 0), 100) / 100) * HEIGHT

  const segments = []
  let current = []
  let previous = null
  for (const p of points) {
    const time = new Date(p.t).getTime()
    if (previous !== null && (time - previous) / 1000 > gapSeconds) {
      segments.push(current)
      current = []
    }
    current.push(p)
    previous = time
  }
  if (current.length) segments.push(current)

  if (points.length === 0) {
    return <div className="chart-empty">No samples stored for this period yet.</div>
  }

  const last = points[points.length - 1]

  return (
    <div className="chart">
      <div className="chart-axis" aria-hidden="true">
        <span>100%</span>
        <span>50%</span>
        <span>0%</span>
      </div>
      <svg
        className="chart-plot"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`${label}: ${points.length} points, latest ${formatPercent(last[field])}%`}
      >
        <line className="chart-grid" x1="0" x2={WIDTH} y1={y(50)} y2={y(50)} />
        <line className="chart-grid" x1="0" x2={WIDTH} y1={HEIGHT - 0.5} y2={HEIGHT - 0.5} />
        {segments.map((seg) =>
          seg.length === 1 ? (
            <circle key={seg[0].t} className="line-dot" cx={x(seg[0].t)} cy={y(seg[0][field])} r="2.5" />
          ) : (
            <g key={seg[0].t}>
              <path
                className="line-area"
                d={`M${x(seg[0].t)},${HEIGHT} ${seg.map((p) => `L${x(p.t)},${y(p[field])}`).join(' ')} L${x(seg[seg.length - 1].t)},${HEIGHT} Z`}
              />
              <polyline className="line-stroke" points={seg.map((p) => `${x(p.t)},${y(p[field])}`).join(' ')} />
            </g>
          ),
        )}
        {typeof threshold === 'number' && (
          <line className="chart-limit" x1="0" x2={WIDTH} y1={y(threshold)} y2={y(threshold)} />
        )}
      </svg>
      <div className="chart-foot" aria-hidden="true">
        <span>{formatDateTime(start)}</span>
        {typeof threshold === 'number' && (
          <span className="chart-key">
            <span className="chart-key-line" /> Limit {threshold}%
          </span>
        )}
        <span>{formatDateTime(end)}</span>
      </div>
    </div>
  )
}
