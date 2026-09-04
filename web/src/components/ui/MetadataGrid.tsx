import type { ReactNode } from 'react'

export interface MetadataEntry {
  label: string
  value: ReactNode
}

interface MetadataGridProps {
  entries: MetadataEntry[]
  columns?: 1 | 2
}

export function MetadataGrid({ entries, columns = 2 }: MetadataGridProps) {
  return (
    <dl className={columns === 2 ? 'grid grid-cols-2 gap-x-6 gap-y-3' : 'grid grid-cols-1 gap-y-3'}>
      {entries.map((entry) => (
        <div key={entry.label}>
          <dt className="text-micro uppercase tracking-wide text-mute">{entry.label}</dt>
          <dd className="mt-0.5 text-caption font-medium text-ink">{entry.value}</dd>
        </div>
      ))}
    </dl>
  )
}
