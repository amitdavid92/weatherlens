import { AlertTriangle, CircleDashed } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Band } from '../api/types'
import { bandClass, FRESHNESS_LABEL, SOURCE_LABEL } from '../format'

export function BandBadge({ band }: { band: Band | null | undefined }) {
  if (!band) return <span className="badge band-none">n/a</span>
  return <span className={`badge ${bandClass(band)}`}>{band}</span>
}

export function PartialTag({ title }: { title?: string | null }) {
  return (
    <span className="tag tag-partial" title={title ?? undefined}>
      <CircleDashed size={12} aria-hidden /> Partial data
    </span>
  )
}

/** Horizontal score bar. Width uses the backend score; the label is the backend display string. */
export function ScoreBar({
  score,
  display,
  band,
  muted,
}: {
  score: number | null
  display: string | null
  band: Band | null
  muted?: boolean
}) {
  const width = score == null ? 0 : Math.max(0, Math.min(100, score))
  return (
    <div className={`scorebar ${muted ? 'is-muted' : ''}`}>
      <div className="scorebar-track" aria-hidden>
        <div className={`scorebar-fill ${bandClass(band)}`} style={{ width: `${width}%` }} />
      </div>
      <span className="scorebar-value num">{display ?? 'n/a'}</span>
    </div>
  )
}

export function FreshnessChips({ freshness }: { freshness: Record<string, string[]> }) {
  const entries = Object.entries(freshness)
  if (!entries.length) return null
  return (
    <span className="chips">
      {entries.map(([src, labels]) => (
        <span key={src} className={`chip fresh-${labels.includes('snapshot') ? 'snapshot' : labels[0]}`}>
          {SOURCE_LABEL[src] ?? src}: {labels.map((l) => FRESHNESS_LABEL[l] ?? l).join(', ')}
        </span>
      ))}
    </span>
  )
}

export function Callout({ tone, icon, title, children }: { tone: 'warn' | 'info' | 'error'; icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className={`callout callout-${tone}`} role={tone === 'error' ? 'alert' : undefined}>
      <span className="callout-icon" aria-hidden>
        {icon ?? <AlertTriangle size={16} />}
      </span>
      <div>
        <strong>{title}</strong>
        {children ? <div className="callout-body">{children}</div> : null}
      </div>
    </div>
  )
}

export function Skeleton({ rows = 4, height = 14 }: { rows?: number; height?: number }) {
  return (
    <div className="skeleton" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton-line" style={{ height, width: `${92 - ((i * 17) % 35)}%` }} />
      ))}
    </div>
  )
}

export function SectionHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="section-header">
      <h2>{title}</h2>
      {children ? <div className="section-actions">{children}</div> : null}
    </div>
  )
}
