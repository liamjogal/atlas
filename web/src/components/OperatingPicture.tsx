import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, where, type AggregateRow, type OntologyDef, type OntologyObject, type Step } from '../api'
import { SEVERITY, relativeTime } from '../format'
import { RankedBars, StatTile, TimeBars, type BarDatum } from './Charts'
import { HazardMap, type Selection } from './HazardMap'
import { ObjectSummary, ObjectView } from './ObjectView'

const MAGNITUDES = [
  { label: 'All', value: 0 },
  { label: 'M2.5+', value: 2.5 },
  { label: 'M4+', value: 4 },
]
const WINDOWS = [
  { label: '24 hours', hours: 24 },
  { label: '7 days', hours: 168 },
]

interface PictureData {
  counties: OntologyObject[]
  quakes: OntologyObject[]
  quakeBuckets: AggregateRow[]
  alertTypes: AggregateRow[]
  alertSeverities: AggregateRow[]
  hotspots: OntologyObject[]
}

function quakeSteps(minMag: number, hours: number): Step[] {
  const since = new Date(Date.now() - hours * 3_600_000).toISOString()
  const steps: Step[] = [where('occurred_at', 'gte', since)]
  if (minMag > 0) steps.push(where('magnitude', 'gte', minMag))
  return steps
}

async function loadPicture(minMag: number, hours: number): Promise<PictureData> {
  const steps = quakeSteps(minMag, hours)
  const [counties, quakes, quakeBuckets, alertTypes, alertSeverities, hotspots] = await Promise.all([
    api.load({ object_type: 'County', steps: [where('active_alert_count', 'gt', 0)], limit: 5000 }),
    api.load({ object_type: 'Earthquake', steps, order_by: 'magnitude', desc: true, limit: 5000 }),
    api.aggregate({
      object_type: 'Earthquake',
      steps,
      group_by: [{ property: 'occurred_at', bucket: hours <= 24 ? 'hour' : 'day' }],
      metrics: [{ op: 'max', property: 'magnitude' }],
    }),
    api.aggregate({ object_type: 'WeatherAlert', group_by: [{ property: 'event' }], limit: 8 }),
    api.aggregate({ object_type: 'WeatherAlert', group_by: [{ property: 'severity' }] }),
    // The fusion question no single feed answers: where is a recent quake AND an active alert?
    api.load({
      object_type: 'County',
      steps: [where('active_alert_count', 'gt', 0), where('recent_quake_count', 'gt', 0)],
      order_by: 'max_alert_severity_rank',
      desc: true,
      limit: 50,
    }),
  ])
  return {
    counties: counties.data,
    quakes: quakes.data,
    quakeBuckets: quakeBuckets.data,
    alertTypes: alertTypes.data,
    alertSeverities: alertSeverities.data,
    hotspots: hotspots.data,
  }
}

/** Every hour or day in the window, zero-filled, so gaps show as gaps instead of disappearing. */
function bucketBars(rows: AggregateRow[], hours: number): BarDatum[] {
  const byHour = hours <= 24
  const stepMs = byHour ? 3_600_000 : 86_400_000
  const counts = new Map(rows.map((r) => [Date.parse(String(r.group.occurred_at)), r]))
  const now = new Date()
  const end = byHour
    ? Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), now.getUTCHours())
    : Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
  const n = byHour ? 24 : 7
  return Array.from({ length: n }, (_, i) => {
    const t = end - (n - 1 - i) * stepMs
    const row = counts.get(t)
    const date = new Date(t)
    const label = byHour
      ? i % 6 === 0 ? date.toLocaleTimeString(undefined, { hour: 'numeric' }) : ''
      : date.toLocaleDateString(undefined, { weekday: 'short', timeZone: 'UTC' })
    const when = byHour
      ? date.toLocaleString(undefined, { weekday: 'short', hour: 'numeric' })
      : date.toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric', timeZone: 'UTC' })
    return {
      key: String(t),
      label,
      value: row?.count ?? 0,
      tooltip: (
        <>
          <div className="tooltip-title">{when}</div>
          <div>{(row?.count ?? 0).toLocaleString()} earthquakes</div>
          {row?.metrics.max_magnitude != null && <div className="muted">Largest M{row.metrics.max_magnitude.toFixed(1)}</div>}
        </>
      ),
    }
  })
}

export function OperatingPicture({ ontology, refreshKey }: { ontology: OntologyDef; refreshKey: string }) {
  const [minMag, setMinMag] = useState(2.5)
  const [hours, setHours] = useState(168)
  const [data, setData] = useState<PictureData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [history, setHistory] = useState<Selection[]>([])
  const [focus, setFocus] = useState<{ lng: number; lat: number; zoom: number } | null>(null)
  const selected = history.at(-1) ?? null

  useEffect(() => {
    let cancelled = false
    loadPicture(minMag, hours)
      .then((d) => {
        if (!cancelled) {
          setData(d)
          setError(null)
        }
      })
      .catch((e) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [minMag, hours, refreshKey])

  const select = useCallback((s: Selection) => setHistory((h) => [...h, s]), [])
  const locate = useCallback((obj: OntologyObject) => {
    setFocus({ lng: obj.longitude as number, lat: obj.latitude as number, zoom: obj.__apiName === 'County' ? 7 : 7.5 })
  }, [])

  const stats = useMemo(() => {
    if (!data) return null
    const severity = Object.fromEntries(data.alertSeverities.map((r) => [r.group.severity, r.count]))
    const largest = data.quakes[0]
    return {
      countiesUnderAlert: data.counties.length,
      severeAlerts: (severity.Severe ?? 0) + (severity.Extreme ?? 0),
      extremeAlerts: severity.Extreme ?? 0,
      quakeCount: data.quakes.length,
      largest,
    }
  }, [data])

  const windowLabel = WINDOWS.find((w) => w.hours === hours)!.label

  return (
    <div className="picture">
      <HazardMap
        counties={data?.counties ?? []}
        quakes={data?.quakes ?? []}
        selected={selected}
        onSelect={(s) => setHistory([s])}
        focus={focus}
      />

      <aside className="panel">
        {selected ? (
          <ObjectView
            key={`${selected.objectType}:${selected.pk}`}
            ontology={ontology}
            selection={selected}
            onNavigate={select}
            onBack={history.length > 1 ? () => setHistory((h) => h.slice(0, -1)) : undefined}
            onClose={() => setHistory([])}
            onLocate={locate}
          />
        ) : (
          <>
            <div className="filters" role="group" aria-label="Earthquake filters">
              <div className="segmented" aria-label="Minimum magnitude">
                {MAGNITUDES.map((m) => (
                  <button key={m.value} type="button" className={m.value === minMag ? 'active' : ''} onClick={() => setMinMag(m.value)}>
                    {m.label}
                  </button>
                ))}
              </div>
              <div className="segmented" aria-label="Time window">
                {WINDOWS.map((w) => (
                  <button key={w.hours} type="button" className={w.hours === hours ? 'active' : ''} onClick={() => setHours(w.hours)}>
                    {w.label}
                  </button>
                ))}
              </div>
            </div>

            {error && <p className="error">Could not load data: {error}</p>}
            {!data && !error && <p className="muted">Loading the live picture…</p>}

            {data && stats && (
              <>
                <div className="stats">
                  <StatTile label="Counties under alert" value={stats.countiesUnderAlert.toLocaleString()} />
                  <StatTile
                    label="Severe or extreme alerts"
                    accent={SEVERITY.Severe.color}
                    value={stats.severeAlerts.toLocaleString()}
                    note={stats.extremeAlerts ? `${stats.extremeAlerts} extreme` : 'None extreme'}
                  />
                  <StatTile label={`Earthquakes, ${windowLabel}`} value={stats.quakeCount.toLocaleString()} note={minMag ? `M${minMag}+` : 'All magnitudes'} />
                  <StatTile
                    label="Largest earthquake"
                    value={stats.largest ? `M${Number(stats.largest.magnitude).toFixed(1)}` : '—'}
                    note={stats.largest ? (stats.largest.place as string) : undefined}
                  />
                </div>

                <section className="card">
                  <h3>Earthquakes per {hours <= 24 ? 'hour' : 'day'}</h3>
                  <TimeBars data={bucketBars(data.quakeBuckets, hours)} />
                </section>

                <section className="card">
                  <h3>
                    Hotspots <span className="muted">· recent quake and active alert</span>
                  </h3>
                  {data.hotspots.length === 0 && <p className="muted small">No county has both right now.</p>}
                  <ul className="link-list">
                    {data.hotspots.slice(0, 8).map((c) => (
                      <li key={c.__primaryKey}>
                        <button
                          type="button"
                          onClick={() => {
                            select({ objectType: 'County', pk: c.__primaryKey })
                            locate(c)
                          }}
                        >
                          <span className="link-title">
                            {c.name as string}, {c.state as string}
                          </span>
                          <span className="link-summary">
                            <span className="badge">
                              <span className="swatch" style={{ background: SEVERITY[c.max_alert_severity as keyof typeof SEVERITY]?.color }} />
                              {c.max_alert_severity as string}
                            </span>
                            <span className="muted"> · M{Number(c.max_quake_magnitude).toFixed(1)} max</span>
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>

                <section className="card">
                  <h3>Active alerts by type</h3>
                  <RankedBars
                    data={data.alertTypes.map((r) => ({
                      key: String(r.group.event),
                      label: String(r.group.event),
                      value: r.count,
                      tooltip: `${r.count} active ${r.group.event} alerts`,
                    }))}
                  />
                </section>

                <section className="card">
                  <h3>Largest earthquakes</h3>
                  <ul className="link-list">
                    {data.quakes.slice(0, 6).map((q) => (
                      <li key={q.__primaryKey}>
                        <button
                          type="button"
                          onClick={() => {
                            select({ objectType: 'Earthquake', pk: q.__primaryKey })
                            locate(q)
                          }}
                        >
                          <span className="link-title">{q.place as string}</span>
                          <span className="link-summary">
                            <ObjectSummary obj={q} />
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                  {data.quakes[0] && (
                    <p className="muted small">Latest data {relativeTime(data.quakes.reduce((a, b) => ((a.updated_at as string) > (b.updated_at as string) ? a : b)).updated_at as string)}</p>
                  )}
                </section>
              </>
            )}
          </>
        )}
      </aside>
    </div>
  )
}
