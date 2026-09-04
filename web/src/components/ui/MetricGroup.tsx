import type { ReactNode } from 'react'

interface MetricGroupProps {
  title?: string
  children: ReactNode
}

export function MetricGroup({ title, children }: MetricGroupProps) {
  return (
    <div className="border border-hairline">
      {title && (
        <div className="border-b border-hairline bg-surface-soft px-3 py-1.5 text-micro font-medium uppercase tracking-wide text-mute">
          {title}
        </div>
      )}
      <div className="px-3">{children}</div>
    </div>
  )
}
