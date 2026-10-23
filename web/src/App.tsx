import { useEffect, useState } from 'react'
import { api, type Health, type OntologyDef } from './api'
import { relativeTime } from './format'
import { ErrorBoundary } from './components/ErrorBoundary'
import { ObjectExplorer } from './components/ObjectExplorer'
import { OperatingPicture } from './components/OperatingPicture'

type Tab = 'picture' | 'explorer'
const HEALTH_POLL_MS = 30_000

export default function App() {
  const [tab, setTab] = useState<Tab>('picture')
  const [ontology, setOntology] = useState<OntologyDef | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [, setTick] = useState(0)

  useEffect(() => {
    api.ontology().then(setOntology).catch((e) => setError(e.message))
    const poll = () =>
      api
        .health()
        .then((h) => {
          setHealth(h)
          setTick((t) => t + 1) // re-render so "synced N min ago" stays current
        })
        .catch(() => undefined)
    poll()
    const id = setInterval(poll, HEALTH_POLL_MS)
    return () => clearInterval(id)
  }, [])

  // Views reload whenever a new sync lands, so the picture stays live without a page refresh.
  const refreshKey = health?.last_sync?.finished_at ?? ''

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden="true">◆</span>
          <span className="brand-name">Atlas</span>
          <span className="muted brand-sub">Live disaster picture</span>
        </div>
        <nav className="tabs" aria-label="Views">
          <button type="button" className={tab === 'picture' ? 'active' : ''} onClick={() => setTab('picture')}>
            Operating picture
          </button>
          <button type="button" className={tab === 'explorer' ? 'active' : ''} onClick={() => setTab('explorer')}>
            Object explorer
          </button>
        </nav>
        <div className="sync" title={health?.last_sync ? Object.entries(health.last_sync.sources).map(([k, v]) => `${k}: ${v}`).join('\n') : undefined}>
          <span className={health?.last_sync ? 'dot live' : 'dot'} />
          {health?.last_sync ? (
            <>
              Synced {relativeTime(health.last_sync.finished_at)}
              {health.sync_every_seconds ? <span className="muted"> · every {Math.round(health.sync_every_seconds / 60)} min</span> : null}
            </>
          ) : (
            <span className="muted">Waiting for first sync</span>
          )}
        </div>
      </header>

      {error && <p className="error page-error">Could not reach the Atlas API: {error}. Is `uv run atlas serve` running?</p>}
      <ErrorBoundary key={tab} label="This view">
        {ontology && tab === 'picture' && <OperatingPicture ontology={ontology} refreshKey={refreshKey} sources={health?.last_sync?.sources ?? {}} />}
        {ontology && tab === 'explorer' && <ObjectExplorer ontology={ontology} refreshKey={refreshKey} />}
      </ErrorBoundary>
    </div>
  )
}
