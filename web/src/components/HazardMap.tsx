import { useEffect, useRef, useState } from 'react'
import { Map as MapLibre, Popup, setWorkerUrl, type GeoJSONSource, type MapGeoJSONFeature } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
// MapLibre v6 ships its tile worker separately; let Vite bundle it and tell MapLibre where it is.
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { feature, mesh } from 'topojson-client'
import type { GeometryCollection, Topology } from 'topojson-specification'
import type { FeatureCollection } from 'geojson'
import countiesTopo from 'us-atlas/counties-10m.json'
import type { OntologyObject } from '../api'
import { FACILITY_KINDS, FACILITY_MIN_ZOOM, SEVERITY, relativeTime } from '../format'
import { WebglHint } from './ErrorBoundary'
import { webglSupported } from './webgl'

export interface Selection {
  objectType: string
  pk: string
}

export interface Viewport {
  west: number
  south: number
  east: number
  north: number
  zoom: number
}

interface Props {
  counties: OntologyObject[]
  quakes: OntologyObject[]
  fires: OntologyObject[]
  facilities: OntologyObject[]
  selected: Selection | null
  onSelect: (selection: Selection) => void
  onViewport: (viewport: Viewport) => void
  focus: { lng: number; lat: number; zoom: number } | null
}

setWorkerUrl(maplibreWorkerUrl)

const BASEMAP = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'
const QUAKE_BLUE = '#3987e5'
// Fires get a hue of their own: the reds and oranges are reserved for alert severity.
const FIRE_COLOR = '#d55181'

const topo = countiesTopo as unknown as Topology<{ counties: GeometryCollection; states: GeometryCollection }>
const countyShapes = feature(topo, topo.objects.counties) as FeatureCollection
const stateLines = mesh(topo, topo.objects.states, (a, b) => a !== b)
// Tooltip text comes from external feeds, so escape it before it goes into HTML.
const esc = (value: unknown) =>
  String(value ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)

const empty: FeatureCollection = { type: 'FeatureCollection', features: [] }

function countyCollection(counties: OntologyObject[]): FeatureCollection {
  const byGeoid = new Map(counties.map((c) => [c.geoid as string, c]))
  return {
    type: 'FeatureCollection',
    features: countyShapes.features.map((f) => {
      const county = byGeoid.get(String(f.id))
      return {
        ...f,
        properties: {
          geoid: String(f.id),
          name: (county?.name as string) ?? f.properties?.name,
          state: county?.state ?? '',
          rank: (county?.max_alert_severity_rank as number) ?? 0,
          severity: county?.max_alert_severity ?? null,
          alerts: (county?.active_alert_count as number) ?? 0,
        },
      }
    }),
  }
}

function quakeCollection(quakes: OntologyObject[]): FeatureCollection {
  const now = Date.now()
  return {
    type: 'FeatureCollection',
    features: quakes.map((q) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [q.longitude as number, q.latitude as number] },
      properties: {
        event_id: q.event_id,
        magnitude: q.magnitude ?? 0,
        place: q.place,
        age_hours: (now - Date.parse(q.occurred_at as string)) / 3_600_000,
      },
    })),
  }
}

function fireCollection(fires: OntologyObject[]): FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: fires.map((f) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [f.longitude as number, f.latitude as number] },
      properties: { detection_id: f.detection_id, frp: f.frp ?? 0, detected_at: f.detected_at },
    })),
  }
}

// Facility marker: a rounded square in the kind's colour with a dark rim (hazards are circles),
// drawn at 2x for crisp edges and registered with the map as an icon image.
function facilityIcon(color: string): ImageData {
  const size = 40
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const g = canvas.getContext('2d')!
  g.fillStyle = '#1a1a19'
  g.beginPath()
  g.roundRect(0, 0, size, size, 10)
  g.fill()
  g.fillStyle = color
  g.beginPath()
  g.roundRect(3, 3, size - 6, size - 6, 8)
  g.fill()
  return g.getImageData(0, 0, size, size)
}

function facilityCollection(facilities: OntologyObject[]): FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: facilities.map((f) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [f.longitude as number, f.latitude as number] },
      properties: {
        facility_id: f.facility_id,
        kind: f.kind,
        name: f.name,
        letter: FACILITY_KINDS[f.kind as string]?.letter ?? '?',
      },
    })),
  }
}

export function HazardMap(props: Props) {
  if (!webglSupported) {
    return (
      <div className="map-wrap">
        <div className="failure" role="alert">
          <strong>The map could not load: this browser has WebGL turned off.</strong>
          <WebglHint />
        </div>
      </div>
    )
  }
  return <MapCanvas {...props} />
}

function MapCanvas({ counties, quakes, fires, facilities, selected, onSelect, onViewport, focus }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibre | null>(null)
  const onSelectRef = useRef(onSelect)
  const onViewportRef = useRef(onViewport)
  const [loaded, setLoaded] = useState(false)
  const [zoom, setZoom] = useState(0)
  const [visibleKinds, setVisibleKinds] = useState<string[]>(Object.keys(FACILITY_KINDS))

  useEffect(() => {
    onSelectRef.current = onSelect
    onViewportRef.current = onViewport
  }, [onSelect, onViewport])

  useEffect(() => {
    const map = new MapLibre({
      container: container.current!,
      style: BASEMAP,
      bounds: [[-125, 24], [-66, 50]], // continental US
      fitBoundsOptions: { padding: 24 },
      attributionControl: { compact: true },
      // Keep the view in the URL (#zoom/lat/lon) so any view can be bookmarked or shared.
      hash: true,
    })
    mapRef.current = map
    map.on('error', (e) => console.error('Map error:', e.error))
    const popup = new Popup({ closeButton: false, closeOnClick: false, className: 'map-tooltip', offset: 10 })

    map.on('load', () => {
      map.addSource('counties', { type: 'geojson', data: empty, promoteId: 'geoid' })
      map.addSource('states', { type: 'geojson', data: stateLines })
      map.addSource('quakes', { type: 'geojson', data: empty })
      map.addSource('fires', { type: 'geojson', data: empty })
      map.addSource('facilities', { type: 'geojson', data: empty })

      const severityColor: unknown[] = ['match', ['get', 'rank']]
      for (const { rank, color } of Object.values(SEVERITY)) severityColor.push(rank, color)
      severityColor.push('transparent')

      // County fills go beneath the basemap's place labels so town names stay readable.
      const firstLabel = map.getStyle().layers.find((l) => l.type === 'symbol')?.id

      // An invisible fill over every county makes any county clickable, alerted or not.
      map.addLayer({ id: 'county-hit', type: 'fill', source: 'counties', paint: { 'fill-opacity': 0 } }, firstLabel)
      map.addLayer({
        id: 'county-alerts',
        type: 'fill',
        source: 'counties',
        filter: ['>', ['get', 'rank'], 0],
        paint: {
          'fill-color': severityColor as never,
          'fill-opacity': ['case', ['boolean', ['feature-state', 'hover'], false], 0.75, 0.5],
        },
      }, firstLabel)
      map.addLayer({
        id: 'state-lines',
        type: 'line',
        source: 'states',
        paint: { 'line-color': '#5f5e5a', 'line-width': 0.6 },
      })
      map.addLayer({
        id: 'county-selected',
        type: 'line',
        source: 'counties',
        filter: ['==', ['get', 'geoid'], ''],
        paint: { 'line-color': '#ffffff', 'line-width': 2 },
      })
      map.addLayer({
        id: 'fires',
        type: 'circle',
        source: 'fires',
        layout: { 'circle-sort-key': ['get', 'frp'] },
        paint: {
          // Sized by fire radiative power (MW): how intensely it is burning. Small at national
          // scale, where ~1,000 detections would otherwise blanket the map.
          'circle-radius': [
            'interpolate', ['linear'], ['zoom'],
            3, ['interpolate', ['linear'], ['get', 'frp'], 0, 1.5, 50, 3, 200, 5],
            8, ['interpolate', ['linear'], ['get', 'frp'], 0, 4, 50, 8, 200, 13],
          ],
          'circle-color': FIRE_COLOR,
          'circle-opacity': 0.8,
          'circle-stroke-color': '#1a1a19',
          'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 3, 0, 6, 1],
        },
      })
      map.addLayer({
        id: 'quakes',
        type: 'circle',
        source: 'quakes',
        layout: { 'circle-sort-key': ['get', 'magnitude'] },
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['get', 'magnitude'], 0, 2, 2.5, 4, 4, 8, 5, 12, 7, 22],
          'circle-color': QUAKE_BLUE,
          // Newer events are more opaque; a week-old event fades back.
          'circle-opacity': ['interpolate', ['linear'], ['get', 'age_hours'], 0, 0.95, 24, 0.75, 168, 0.3],
          'circle-stroke-color': '#1a1a19',
          'circle-stroke-width': 1,
        },
      })
      map.addLayer({
        id: 'quake-selected',
        type: 'circle',
        source: 'quakes',
        filter: ['==', ['get', 'event_id'], ''],
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['get', 'magnitude'], 0, 5, 2.5, 7, 4, 11, 5, 15, 7, 25],
          'circle-color': 'transparent',
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 2,
        },
      })
      // Facilities: a colour-coded square per kind with its letter, only at city scale.
      for (const [kind, { color }] of Object.entries(FACILITY_KINDS)) {
        map.addImage(`facility-${kind}`, facilityIcon(color), { pixelRatio: 2 })
      }
      // Reuse a font the basemap already serves, so the letters render without extra glyph requests.
      const fontOf = (layer: { layout?: unknown }) => (layer.layout as Record<string, unknown> | undefined)?.['text-font']
      const labelFont = (map.getStyle().layers.map(fontOf).find(Array.isArray) as string[] | undefined) ?? ['Open Sans Bold']
      map.addLayer({
        id: 'facilities',
        type: 'symbol',
        source: 'facilities',
        minzoom: FACILITY_MIN_ZOOM,
        layout: {
          'icon-image': ['concat', 'facility-', ['get', 'kind']],
          'icon-allow-overlap': true,
          'icon-ignore-placement': true,
          'text-field': ['get', 'letter'],
          'text-font': labelFont,
          'text-size': 10,
          'text-allow-overlap': true,
          'text-ignore-placement': true,
        },
        // White letters with a dark halo stay readable on every one of the four colours.
        paint: { 'text-color': '#ffffff', 'text-halo-color': '#0d0d0d', 'text-halo-width': 1 },
      })
      map.addLayer({
        id: 'point-selected',
        type: 'circle',
        source: 'facilities',
        filter: ['==', ['get', 'facility_id'], ''],
        paint: { 'circle-radius': 14, 'circle-color': 'transparent', 'circle-stroke-color': '#ffffff', 'circle-stroke-width': 2 },
      })
      setLoaded(true)
      reportViewport()
    })

    const reportViewport = () => {
      const b = map.getBounds()
      setZoom(map.getZoom())
      onViewportRef.current({ west: b.getWest(), south: b.getSouth(), east: b.getEast(), north: b.getNorth(), zoom: map.getZoom() })
    }
    map.on('moveend', reportViewport)

    let hovered: string | number | undefined
    const pick = (point: { x: number; y: number }): MapGeoJSONFeature | undefined => {
      const layers = ['facilities', 'quakes', 'fires', 'county-hit'].filter((id) => map.getLayer(id))
      const [hit] = map.queryRenderedFeatures([point.x, point.y], { layers })
      return hit
    }

    map.on('mousemove', (e) => {
      const hit = pick(e.point)
      if (hovered !== undefined) map.setFeatureState({ source: 'counties', id: hovered }, { hover: false })
      hovered = undefined
      if (!hit) {
        popup.remove()
        map.getCanvas().style.cursor = ''
        return
      }
      map.getCanvas().style.cursor = 'pointer'
      const p = hit.properties
      let html: string
      if (hit.layer.id === 'quakes') {
        html = `<strong>M${Number(p.magnitude).toFixed(1)}</strong> ${esc(p.place)}`
      } else if (hit.layer.id === 'fires') {
        html = `<strong>Fire detection</strong> ${relativeTime(p.detected_at)}<br/>Intensity ${Number(p.frp).toFixed(1)} MW`
      } else if (hit.layer.id === 'facilities') {
        html = `<strong>${esc(p.name)}</strong><br/>${esc(FACILITY_KINDS[p.kind]?.label.replace(/s$/, '') ?? p.kind)}`
      } else {
        hovered = p.geoid
        map.setFeatureState({ source: 'counties', id: p.geoid }, { hover: true })
        const alerts = p.alerts ? `${p.alerts} active alert${p.alerts > 1 ? 's' : ''} · worst: ${esc(p.severity)}` : 'No active alerts'
        html = `<strong>${esc(p.name)}${p.state ? `, ${esc(p.state)}` : ''}</strong><br/>${alerts}`
      }
      popup.setLngLat(e.lngLat).setHTML(html).addTo(map)
    })
    map.on('mouseout', () => popup.remove())
    map.on('click', (e) => {
      const hit = pick(e.point)
      if (!hit) return
      const p = hit.properties
      if (hit.layer.id === 'quakes') onSelectRef.current({ objectType: 'Earthquake', pk: p.event_id })
      else if (hit.layer.id === 'fires') onSelectRef.current({ objectType: 'FireDetection', pk: p.detection_id })
      else if (hit.layer.id === 'facilities') onSelectRef.current({ objectType: 'Facility', pk: p.facility_id })
      else onSelectRef.current({ objectType: 'County', pk: p.geoid })
    })

    return () => map.remove()
  }, [])

  useEffect(() => {
    if (!loaded) return
    ;(mapRef.current!.getSource('counties') as GeoJSONSource).setData(countyCollection(counties))
  }, [loaded, counties])

  useEffect(() => {
    if (!loaded) return
    ;(mapRef.current!.getSource('quakes') as GeoJSONSource).setData(quakeCollection(quakes))
  }, [loaded, quakes])

  useEffect(() => {
    if (!loaded) return
    ;(mapRef.current!.getSource('fires') as GeoJSONSource).setData(fireCollection(fires))
  }, [loaded, fires])

  useEffect(() => {
    if (!loaded) return
    ;(mapRef.current!.getSource('facilities') as GeoJSONSource).setData(facilityCollection(facilities))
  }, [loaded, facilities])

  useEffect(() => {
    if (!loaded) return
    const kindFilter = ['in', ['get', 'kind'], ['literal', visibleKinds]] as never
    mapRef.current!.setFilter('facilities', kindFilter)
  }, [loaded, visibleKinds])

  useEffect(() => {
    if (!loaded) return
    const map = mapRef.current!
    const county = selected?.objectType === 'County' ? selected.pk : ''
    const quake = selected?.objectType === 'Earthquake' ? selected.pk : ''
    map.setFilter('county-selected', ['==', ['get', 'geoid'], county])
    map.setFilter('quake-selected', ['==', ['get', 'event_id'], quake])
    map.setFilter('point-selected', ['==', ['get', 'facility_id'], selected?.objectType === 'Facility' ? selected.pk : ''])
  }, [loaded, selected])

  useEffect(() => {
    if (focus) mapRef.current?.flyTo({ center: [focus.lng, focus.lat], zoom: focus.zoom, duration: 1200 })
  }, [focus])

  return (
    <div className="map-wrap">
      <div ref={container} className="map" />
      <div className="map-legend" aria-label="Map legend">
        <div className="legend-title">Worst active alert</div>
        {Object.entries(SEVERITY).map(([name, { color }]) => (
          <div key={name} className="legend-row">
            <span className="swatch" style={{ background: color }} />
            {name}
          </div>
        ))}
        <div className="legend-title" style={{ marginTop: 8 }}>Earthquakes and fires</div>
        <div className="legend-row">
          <span className="swatch round" style={{ background: QUAKE_BLUE }} />
          Quake: size = magnitude, faded = older
        </div>
        <div className="legend-row">
          <span className="swatch round" style={{ background: FIRE_COLOR }} />
          Fire (24 h): size = intensity
        </div>
      </div>
      <div className="facility-toggles" role="group" aria-label="Facilities">
        <div className="legend-title">
          Facilities{zoom < FACILITY_MIN_ZOOM && <span className="muted"> · zoom in to show</span>}
        </div>
        {Object.entries(FACILITY_KINDS).map(([kind, { letter, label, color }]) => (
          <label key={kind} className="legend-row toggle">
            <input
              type="checkbox"
              checked={visibleKinds.includes(kind)}
              onChange={(e) =>
                setVisibleKinds((v) => (e.target.checked ? [...v, kind] : v.filter((k) => k !== kind)))
              }
            />
            <span className="facility-badge" style={{ background: color }} aria-hidden="true">{letter}</span>
            {label}
          </label>
        ))}
      </div>
    </div>
  )
}
