// Typed client for the Atlas Ontology API. The app never talks to tables, only to
// object types, links and object sets, exactly like an OSDK client would.

export type PropertyType = 'string' | 'integer' | 'double' | 'boolean' | 'timestamp'

export interface PropertyDef {
  type: PropertyType
  description: string | null
}

export interface LinkSideDef {
  target: string
  many: boolean
}

export interface ObjectTypeDef {
  description: string | null
  backing_dataset: string
  primary_key: string
  title_property: string
  properties: Record<string, PropertyDef>
  links: Record<string, LinkSideDef>
}

export interface OntologyDef {
  object_types: Record<string, ObjectTypeDef>
}

export type OntologyObject = {
  __apiName: string
  __primaryKey: string
  __title: string | null
} & Record<string, unknown>

export interface Filter {
  property: string
  op: 'eq' | 'ne' | 'gt' | 'gte' | 'lt' | 'lte' | 'contains' | 'is_null' | 'is_not_null'
  value?: unknown
}

export type Step = { where: Filter } | { search_around: string }

export interface ObjectPage<T = OntologyObject> {
  total: number
  data: T[]
}

export interface AggregateRow {
  group: Record<string, string | number | null>
  metrics: Record<string, number | null>
  count: number
}

export interface Health {
  status: string
  object_store: 'postgres' | 'duckdb'
  sync_every_seconds: number | null
  index_matches_ontology: boolean
  last_sync: {
    finished_at: string
    status: string
    sources: Record<string, string>
    datasets: Record<string, number>
    objects: Record<string, number>
  } | null
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail ?? `${response.status} ${response.statusText}`)
  }
  return response.json()
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })

export const api = {
  health: () => request<Health>('/api/health'),

  ontology: () => request<OntologyDef>('/api/ontology'),

  get: (objectType: string, pk: string) =>
    request<OntologyObject>(`/api/objects/${objectType}/${encodeURIComponent(pk)}`),

  links: (objectType: string, pk: string, link: string, opts: { orderBy?: string; desc?: boolean; limit?: number } = {}) => {
    const params = new URLSearchParams({ limit: String(opts.limit ?? 50) })
    if (opts.orderBy) params.set('order_by', opts.orderBy)
    if (opts.desc) params.set('desc', 'true')
    return request<{ data: OntologyObject[] }>(
      `/api/objects/${objectType}/${encodeURIComponent(pk)}/links/${link}?${params}`,
    )
  },

  load: <T = OntologyObject>(body: {
    object_type: string
    steps?: Step[]
    order_by?: string
    desc?: boolean
    limit?: number
    offset?: number
  }) => post<ObjectPage<T> & { object_type: string }>('/api/objectSets/load', body),

  aggregate: (body: {
    object_type: string
    steps?: Step[]
    group_by?: { property: string; bucket?: 'hour' | 'day' | 'week' | 'month' }[]
    metrics?: { op: 'avg' | 'min' | 'max' | 'sum'; property: string }[]
    limit?: number
  }) => post<{ object_type: string; data: AggregateRow[] }>('/api/objectSets/aggregate', body),
}

export const where = (property: string, op: Filter['op'], value?: unknown): Step => ({
  where: { property, op, value },
})
export const searchAround = (link: string): Step => ({ search_around: link })
