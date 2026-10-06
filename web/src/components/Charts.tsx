import { useEffect, useRef, useState, type ReactNode } from 'react'

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(ref.current!)
    return () => observer.disconnect()
  }, [])
  return [ref, width] as const
}

function niceTicks(max: number, count = 3): number[] {
  if (max <= 0) return [0]
  const raw = max / count
  const magnitude = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 5, 10].map((m) => m * magnitude).find((s) => s >= raw)!
  return Array.from({ length: Math.ceil(max / step) + 1 }, (_, i) => i * step)
}

// A bar whose data end (the top) is rounded and whose baseline end stays square.
function barPath(x: number, y: number, w: number, h: number, r = 4) {
  const radius = Math.min(r, w / 2, h)
  return `M${x},${y + h}V${y + radius}Q${x},${y} ${x + radius},${y}H${x + w - radius}Q${x + w},${y} ${x + w},${y + radius}V${y + h}Z`
}

export interface BarDatum {
  key: string
  label: string
  value: number
  tooltip: ReactNode
}

/** Vertical bars over time, one series: the title names it, so no legend. */
export function TimeBars({ data, height = 150 }: { data: BarDatum[]; height?: number }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const pad = { left: 32, right: 4, top: 8, bottom: 22 }
  const ticks = niceTicks(Math.max(1, ...data.map((d) => d.value)))
  const yMax = ticks.at(-1)!
  const plotW = Math.max(0, width - pad.left - pad.right)
  const plotH = height - pad.top - pad.bottom
  const band = data.length ? plotW / data.length : 0
  const barW = Math.max(2, band - 2 * Math.max(2, band * 0.15))
  const y = (v: number) => pad.top + plotH - (v / yMax) * plotH

  return (
    <div ref={ref} className="chart" onMouseLeave={() => setHover(null)}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label="Bar chart">
          {ticks.map((t) => (
            <g key={t}>
              <line x1={pad.left} x2={width - pad.right} y1={y(t)} y2={y(t)} className={t === 0 ? 'axis' : 'grid'} />
              <text x={pad.left - 6} y={y(t)} dy="0.32em" textAnchor="end" className="tick">
                {t.toLocaleString()}
              </text>
            </g>
          ))}
          {data.map((d, i) => {
            const x = pad.left + i * band + (band - barW) / 2
            return (
              <g key={d.key}>
                {d.value > 0 && (
                  <path
                    d={barPath(x, y(d.value), barW, y(0) - y(d.value))}
                    className="bar"
                    opacity={hover === null || hover === i ? 1 : 0.45}
                  />
                )}
                <text x={x + barW / 2} y={height - 6} textAnchor="middle" className="tick">
                  {d.label}
                </text>
                {/* The hit target is the whole column, wider than the bar itself. */}
                <rect
                  x={pad.left + i * band}
                  y={pad.top}
                  width={band}
                  height={plotH}
                  fill="transparent"
                  onMouseEnter={() => setHover(i)}
                />
              </g>
            )
          })}
        </svg>
      )}
      {hover !== null && data[hover] && (
        <div
          className="tooltip"
          style={{
            left: Math.min(Math.max(pad.left + (hover + 0.5) * band, 70), width - 70),
            top: Math.max(0, y(data[hover].value) - 8),
          }}
        >
          {data[hover].tooltip}
        </div>
      )}
    </div>
  )
}

/** Horizontal ranked bars for categories: label, bar, value. */
export function RankedBars({ data, onSelect }: { data: BarDatum[]; onSelect?: (key: string) => void }) {
  const max = Math.max(1, ...data.map((d) => d.value))
  return (
    <div className="ranked">
      {data.map((d) => (
        <button
          key={d.key}
          type="button"
          className="ranked-row"
          title={typeof d.tooltip === 'string' ? d.tooltip : undefined}
          onClick={() => onSelect?.(d.key)}
          disabled={!onSelect}
        >
          <span className="ranked-label">{d.label}</span>
          <span className="ranked-track">
            <span className="ranked-bar" style={{ width: `${(d.value / max) * 100}%` }} />
          </span>
          <span className="ranked-value">{d.value.toLocaleString()}</span>
        </button>
      ))}
    </div>
  )
}

export function StatTile({ label, value, note, accent }: { label: string; value: ReactNode; note?: ReactNode; accent?: string }) {
  return (
    <div className="stat">
      <div className="stat-label">
        {accent && <span className="swatch" style={{ background: accent }} />}
        {label}
      </div>
      <div className="stat-value">{value}</div>
      {note && <div className="stat-note">{note}</div>}
    </div>
  )
}
