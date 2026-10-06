import { useEffect, useState } from 'react'
import { api, type OntologyDef, type OntologyObject } from '../api'
import { DEFAULT_ORDER, formatValue, humanize, relativeTime, severityColor } from '../format'
import type { Selection } from './HazardMap'


const LONG_TEXT = 140

export function SeverityBadge({ severity }: { severity: unknown }) {
  if (!severity) return <span className="muted">None</span>
  return (
    <span className="badge">
      <span className="swatch" style={{ background: severityColor(severity) }} />
      {String(severity)}
    </span>
  )
}

/** One line that makes a linked object recognisable without opening it. */
export function ObjectSummary({ obj }: { obj: OntologyObject }) {
  switch (obj.__apiName) {
    case 'Earthquake':
      return (
        <>
          <strong>M{Number(obj.magnitude ?? 0).toFixed(1)}</strong>
          <span className="muted"> · {relativeTime(obj.occurred_at as string)}</span>
        </>
      )
    case 'WeatherAlert':
      return <SeverityBadge severity={obj.severity} />
    case 'County':
      return (
        <span className="muted">
          {obj.state as string}
          {Number(obj.active_alert_count) > 0 && ` · ${obj.active_alert_count} alerts`}
        </span>
      )
    default:
      return null
  }
}

interface Props {
  ontology: OntologyDef
  selection: Selection
  onNavigate: (selection: Selection) => void
  onBack?: () => void
  onClose?: () => void
  onLocate?: (obj: OntologyObject) => void
}

export function ObjectView({ ontology, selection, onNavigate, onBack, onClose, onLocate }: Props) {
  const def = ontology.object_types[selection.objectType]
  const [obj, setObj] = useState<OntologyObject | null>(null)
  const [links, setLinks] = useState<Record<string, OntologyObject[]>>({})
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // Callers key this component by selection, so state starts fresh for every object.
    let cancelled = false
    api
      .get(selection.objectType, selection.pk)
      .then((o) => !cancelled && setObj(o))
      .catch((e) => !cancelled && setError(e.message))
    for (const [name, side] of Object.entries(def.links)) {
      const order = DEFAULT_ORDER[side.target]
      api
        .links(selection.objectType, selection.pk, name, { orderBy: order?.orderBy, desc: order?.desc, limit: 100 })
        .then((r) => !cancelled && setLinks((prev) => ({ ...prev, [name]: r.data })))
        .catch(() => undefined)
    }
    return () => {
      cancelled = true
    }
  }, [selection.objectType, selection.pk, def])

  return (
    <div className="object-view">
      <div className="object-nav">
        {onBack && (
          <button type="button" className="ghost" onClick={onBack}>
            ← Back
          </button>
        )}
        <span className="type-chip">{selection.objectType}</span>
        {onClose && (
          <button type="button" className="ghost close" onClick={onClose} aria-label="Close">
            ×
          </button>
        )}
      </div>

      {error && <p className="error">{error}</p>}
      {!obj && !error && <p className="muted">Loading…</p>}
      {obj && (
        <>
          <h2 className="object-title">{obj.__title ?? obj.__primaryKey}</h2>
          {onLocate && obj.latitude != null && (
            <button type="button" className="link-button" onClick={() => onLocate(obj)}>
              Show on map
            </button>
          )}

          <section>
            <h3>Links</h3>
            {Object.entries(def.links).map(([name, side]) => {
              const items = links[name]
              return (
                <div key={name} className="link-group">
                  <div className="link-head">
                    {humanize(name)} <span className="muted">→ {side.target}</span>
                    <span className="count">{items ? items.length : '…'}</span>
                  </div>
                  {items?.length === 0 && <div className="muted small">None linked</div>}
                  <ul className="link-list">
                    {items?.slice(0, 25).map((linked) => (
                      <li key={linked.__primaryKey}>
                        <button
                          type="button"
                          onClick={() => onNavigate({ objectType: linked.__apiName, pk: linked.__primaryKey })}
                        >
                          <span className="link-title">{linked.__title ?? linked.__primaryKey}</span>
                          <span className="link-summary">
                            <ObjectSummary obj={linked} />
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                  {items && items.length > 25 && <div className="muted small">+ {items.length - 25} more</div>}
                </div>
              )
            })}
          </section>

          <section>
            <h3>Properties</h3>
            <dl className="props">
              {Object.entries(def.properties).map(([name, prop]) => {
                const value = obj[name]
                const long = typeof value === 'string' && value.length > LONG_TEXT
                return (
                  <div key={name} className={long ? 'prop long' : 'prop'}>
                    <dt title={prop.description ?? undefined}>{humanize(name)}</dt>
                    <dd>
                      {name.includes('severity') && prop.type === 'string' ? (
                        <SeverityBadge severity={value} />
                      ) : name === 'url' && value ? (
                        <a href={value as string} target="_blank" rel="noreferrer">
                          USGS event page
                        </a>
                      ) : (
                        formatValue(value, prop.type)
                      )}
                    </dd>
                  </div>
                )
              })}
            </dl>
          </section>
        </>
      )}
    </div>
  )
}
