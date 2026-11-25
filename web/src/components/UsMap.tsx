import { geoAlbersUsa, geoPath } from 'd3-geo'
import type { FeatureCollection, MultiLineString } from 'geojson'
import { useMemo, useState } from 'react'
import { feature, mesh } from 'topojson-client'
import type { GeometryCollection, Topology } from 'topojson-specification'
import statesTopo from 'us-atlas/states-albers-10m.json'
import type { Band, HazardKey, OverviewHub } from '../api/types'
import { bandClass, shortName } from '../format'

// us-atlas "albers" files are pre-projected with geoAlbersUsa().scale(1300).translate([487.5, 305])
// on a 975×610 canvas, so hub coordinates use the same projection. Self-contained: no tiles/keys.
const W = 975
const H = 610
const projection = geoAlbersUsa().scale(1300).translate([487.5, 305])
const topo = statesTopo as unknown as Topology<{ states: GeometryCollection; nation: GeometryCollection }>

export function UsMap({
  hubs,
  scope,
  selected,
  onSelect,
}: {
  hubs: OverviewHub[]
  scope: 'overall' | HazardKey
  selected: string | null
  onSelect: (hubId: string) => void
}) {
  const [hover, setHover] = useState<string | null>(null)
  const { nationPath, bordersPath } = useMemo(() => {
    const path = geoPath()
    const nation = feature(topo, topo.objects.nation) as unknown as FeatureCollection
    const borders = mesh(topo, topo.objects.states, (a, b) => a !== b) as MultiLineString
    return { nationPath: path(nation) ?? '', bordersPath: path(borders) ?? '' }
  }, [])

  const points = hubs
    .map((h) => {
      const xy = projection([h.longitude, h.latitude])
      const s = scope === 'overall' ? h.overall : h.hazards[scope]
      return xy ? { hub: h, x: xy[0], y: xy[1], band: s.band as Band | null, partial: s.status !== 'complete', display: s.score_display } : null
    })
    .filter((p): p is NonNullable<typeof p> => p !== null)
    // draw selected/hovered last so their labels sit on top
    .sort((a, b) => Number(a.hub.hub_id === (hover ?? selected)) - Number(b.hub.hub_id === (hover ?? selected)))

  const focus = points.find((p) => p.hub.hub_id === (hover ?? selected))

  return (
    <svg className="usmap" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Map of the illustrative hubs in the contiguous United States">
      <path d={nationPath} className="usmap-nation" />
      <path d={bordersPath} className="usmap-borders" />
      {points.map((p) => {
        const isSel = p.hub.hub_id === selected
        return (
          <g
            key={p.hub.hub_id}
            className={`usmap-hub ${isSel ? 'is-selected' : ''}`}
            transform={`translate(${p.x},${p.y})`}
            tabIndex={0}
            role="button"
            aria-label={`${p.hub.name}: ${p.display ?? 'n/a'}${p.band ? ` (${p.band})` : ''}${p.partial ? ', partial data' : ''}`}
            onClick={() => onSelect(p.hub.hub_id)}
            onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onSelect(p.hub.hub_id))}
            onMouseEnter={() => setHover(p.hub.hub_id)}
            onMouseLeave={() => setHover(null)}
          >
            {isSel && <circle r={22} className="usmap-halo" />}
            <circle r={13} className={`usmap-dot ${bandClass(p.band)} ${p.partial ? 'is-partial' : ''}`} />
          </g>
        )
      })}
      {focus &&
        (() => {
          const label = `${shortName(focus.hub.name)} · ${focus.display ?? 'n/a'} · ${focus.band ?? 'n/a'}${focus.partial ? ' (partial)' : ''}`
          const w = Math.max(120, label.length * 8.4 + 24)
          // keep the tooltip inside the map horizontally
          const left = focus.x - w / 2
          const right = focus.x + w / 2
          const dx = left < 6 ? 6 - left : right > W - 6 ? W - 6 - right : 0
          return (
            <g transform={`translate(${focus.x + dx},${focus.y - 26})`} className="usmap-label" pointerEvents="none">
              <rect x={-w / 2} y={-24} width={w} height={30} rx={6} />
              <text textAnchor="middle" y={-4}>
                {label}
              </text>
            </g>
          )
        })()}
    </svg>
  )
}
