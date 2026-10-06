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
import { SEVERITY } from '../format'

export interface Selection {
  objectType: string
  pk: string
}

interface Props {
  counties: OntologyObject[]
  quakes: OntologyObject[]
  selected: Selection | null
  onSelect: (selection: Selection) => void
  focus: { lng: number; lat: number; zoom: number } | null
}

setWorkerUrl(maplibreWorkerUrl)

const BASEMAP = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'
const QUAKE_BLUE = '#3987e5'

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

export function HazardMap({ counties, quakes, selected, onSelect, focus }: Props) {
  const container = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibre | null>(null)
  const onSelectRef = useRef(onSelect)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    onSelectRef.current = onSelect
  }, [onSelect])

  useEffect(() => {
    const map = new MapLibre({
      container: container.current!,
      style: BASEMAP,
      bounds: [[-125, 24], [-66, 50]], // continental US
      fitBoundsOptions: { padding: 24 },
      attributionControl: { compact: true },
    })
    mapRef.current = map
    map.on('error', (e) => console.error('Map error:', e.error))
    const popup = new Popup({ closeButton: false, closeOnClick: false, className: 'map-tooltip', offset: 10 })

    map.on('load', () => {
      map.addSource('counties', { type: 'geojson', data: empty, promoteId: 'geoid' })
      map.addSource('states', { type: 'geojson', data: stateLines })
      map.addSource('quakes', { type: 'geojson', data: empty })

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
      setLoaded(true)
    })

    let hovered: string | number | undefined
    const pick = (point: { x: number; y: number }): MapGeoJSONFeature | undefined => {
      const [hit] = map.queryRenderedFeatures([point.x, point.y], { layers: ['quakes', 'county-hit'] })
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
      if (hit.layer.id === 'quakes') onSelectRef.current({ objectType: 'Earthquake', pk: hit.properties.event_id })
      else onSelectRef.current({ objectType: 'County', pk: hit.properties.geoid })
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
    const map = mapRef.current!
    const county = selected?.objectType === 'County' ? selected.pk : ''
    const quake = selected?.objectType === 'Earthquake' ? selected.pk : ''
    map.setFilter('county-selected', ['==', ['get', 'geoid'], county])
    map.setFilter('quake-selected', ['==', ['get', 'event_id'], quake])
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
        <div className="legend-title" style={{ marginTop: 8 }}>Earthquakes</div>
        <div className="legend-row">
          <span className="swatch round" style={{ background: QUAKE_BLUE }} />
          Size = magnitude, faded = older
        </div>
      </div>
    </div>
  )
}
