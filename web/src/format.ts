import type { PropertyType } from './api'

// NWS severity is a status scale, so it uses the reserved status colours and is
// always shown next to its label, never by colour alone.
export const SEVERITY = {
  Extreme: { rank: 4, color: '#d03b3b' },
  Severe: { rank: 3, color: '#ec835a' },
  Moderate: { rank: 2, color: '#fab219' },
  Minor: { rank: 1, color: '#898781' },
} as const

export type Severity = keyof typeof SEVERITY

export const severityColor = (severity: unknown) =>
  SEVERITY[severity as Severity]?.color ?? '#383835'

export function relativeTime(iso: string, now = Date.now()): string {
  const minutes = Math.round((now - Date.parse(iso)) / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours} h ago`
  return `${Math.round(hours / 24)} d ago`
}

const dateTime = new Intl.DateTimeFormat(undefined, {
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
})

export function formatValue(value: unknown, type: PropertyType): string {
  if (value === null || value === undefined || value === '') return '—'
  switch (type) {
    case 'timestamp':
      return dateTime.format(new Date(value as string))
    case 'double':
      return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })
    case 'integer':
      return Number(value).toLocaleString()
    case 'boolean':
      return value ? 'Yes' : 'No'
    default:
      return String(value)
  }
}

export const humanize = (name: string) =>
  name
    .replace(/_/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/^./, (c) => c.toUpperCase())

// The most useful default ordering for lists of each object type.
export const DEFAULT_ORDER: Record<string, { orderBy: string; desc: boolean }> = {
  Earthquake: { orderBy: 'occurred_at', desc: true },
  WeatherAlert: { orderBy: 'sent_at', desc: true },
  County: { orderBy: 'active_alert_count', desc: true },
  Facility: { orderBy: 'name', desc: false },
  FireDetection: { orderBy: 'detected_at', desc: true },
}

// Facility kinds are told apart by a letter on the map, never by colour alone.
export const FACILITY_KINDS: Record<string, { letter: string; label: string }> = {
  hospital: { letter: 'H', label: 'Hospitals' },
  shelter: { letter: 'S', label: 'Shelters' },
  fire_station: { letter: 'F', label: 'Fire stations' },
  school: { letter: 'E', label: 'Schools' },
}

// Facilities only make sense (and only load) once the map is zoomed in to city scale.
export const FACILITY_MIN_ZOOM = 7

export const formatPopulation = (n: unknown) => {
  const v = Number(n)
  if (!Number.isFinite(v)) return '—'
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`
  if (v >= 1e3) return `${Math.round(v / 1e3)}k`
  return v.toLocaleString()
}
