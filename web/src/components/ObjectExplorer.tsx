import { useEffect, useMemo, useState } from 'react'
import { api, where, type OntologyDef, type OntologyObject } from '../api'
import { DEFAULT_ORDER, formatValue, humanize } from '../format'
import type { Selection } from './HazardMap'
import { SeverityBadge, ObjectView } from './ObjectView'

const PAGE_SIZE = 50
const HIDDEN_COLUMNS = new Set(['description', 'instruction', 'url', 'latitude', 'longitude'])
const MAX_COLUMNS = 6

export function ObjectExplorer({ ontology, refreshKey }: { ontology: OntologyDef; refreshKey: string }) {
  const typeNames = Object.keys(ontology.object_types)
  const [objectType, setObjectType] = useState(typeNames[0])
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<{ by: string; desc: boolean } | null>(null)
  const [page, setPage] = useState(0)
  const [result, setResult] = useState<{ total: number; data: OntologyObject[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [history, setHistory] = useState<Selection[]>([])
  const def = ontology.object_types[objectType]

  const columns = useMemo(() => {
    // The primary key is usually an opaque id; it stays visible in the object view.
    const rest = Object.keys(def.properties).filter(
      (p) => p !== def.title_property && p !== def.primary_key && !HIDDEN_COLUMNS.has(p) && !p.endsWith('_rank'),
    )
    return [def.title_property, ...rest].slice(0, MAX_COLUMNS)
  }, [def])

  useEffect(() => {
    for (const name of Object.keys(ontology.object_types)) {
      api.load({ object_type: name, limit: 1 }).then((r) => setCounts((c) => ({ ...c, [name]: r.total })))
    }
  }, [ontology, refreshKey])

  useEffect(() => {
    let cancelled = false
    const query = search.trim()
    api
      .load({
        object_type: objectType,
        steps: query ? [where(def.title_property, 'contains', query)] : [],
        order_by: sort?.by ?? DEFAULT_ORDER[objectType]?.orderBy,
        desc: sort?.desc ?? DEFAULT_ORDER[objectType]?.desc,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      })
      .then((r) => {
        if (!cancelled) {
          setResult(r)
          setError(null)
        }
      })
      .catch((e) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [objectType, def, search, sort, page, refreshKey])

  const chooseType = (name: string) => {
    setObjectType(name)
    setSearch('')
    setSort(null)
    setPage(0)
    setResult(null)
  }

  const toggleSort = (column: string) => {
    setPage(0)
    setSort((s) => (s?.by === column ? { by: column, desc: !s.desc } : { by: column, desc: def.properties[column].type !== 'string' }))
  }

  const pages = result ? Math.max(1, Math.ceil(result.total / PAGE_SIZE)) : 1
  const selected = history.at(-1)

  return (
    <div className="explorer">
      <nav className="type-list" aria-label="Object types">
        <div className="section-label">Object types</div>
        {typeNames.map((name) => (
          <button key={name} type="button" className={name === objectType ? 'type active' : 'type'} onClick={() => chooseType(name)}>
            <span className="type-name">{name}</span>
            <span className="count">{counts[name]?.toLocaleString() ?? '…'}</span>
            <span className="type-desc">{ontology.object_types[name].description}</span>
          </button>
        ))}
        <div className="section-label" style={{ marginTop: 16 }}>Backed by</div>
        <code className="muted small">{def.backing_dataset}</code>
      </nav>

      <section className="table-pane">
        <div className="table-toolbar">
          <input
            type="search"
            placeholder={`Search ${objectType} by ${humanize(def.title_property).toLowerCase()}…`}
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPage(0)
            }}
          />
          <span className="muted small">{result ? `${result.total.toLocaleString()} objects` : ''}</span>
        </div>
        {error && <p className="error">{error}</p>}
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c} title={def.properties[c].description ?? undefined}>
                    <button type="button" onClick={() => toggleSort(c)}>
                      {humanize(c)}
                      {sort?.by === c ? (sort.desc ? ' ↓' : ' ↑') : ''}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result?.data.map((obj) => (
                <tr
                  key={obj.__primaryKey}
                  className={selected?.pk === obj.__primaryKey ? 'selected' : ''}
                  onClick={() => setHistory([{ objectType, pk: obj.__primaryKey }])}
                >
                  {columns.map((c) => {
                    const type = def.properties[c].type
                    return (
                      <td key={c} className={type === 'double' || type === 'integer' ? 'num' : ''}>
                        {c.includes('severity') ? <SeverityBadge severity={obj[c]} /> : formatValue(obj[c], type)}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="pager">
          <button type="button" className="ghost" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
            ← Prev
          </button>
          <span className="muted small">
            Page {page + 1} of {pages}
          </span>
          <button type="button" className="ghost" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>
            Next →
          </button>
        </div>
      </section>

      <aside className="panel">
        {selected ? (
          <ObjectView
            key={`${selected.objectType}:${selected.pk}`}
            ontology={ontology}
            selection={selected}
            onNavigate={(s) => setHistory((h) => [...h, s])}
            onBack={history.length > 1 ? () => setHistory((h) => h.slice(0, -1)) : undefined}
            onClose={() => setHistory([])}
          />
        ) : (
          <p className="muted empty">Select an object to see its properties and follow its links.</p>
        )}
      </aside>
    </div>
  )
}
