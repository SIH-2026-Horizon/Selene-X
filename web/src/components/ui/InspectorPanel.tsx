import type { ReactNode } from 'react'

interface InspectorPanelProps {
  title: string
  onClose?: () => void
  children: ReactNode
}

export function InspectorPanel({ title, onClose, children }: InspectorPanelProps) {
  return (
    <aside className="flex h-full flex-col border-l border-hairline bg-canvas" aria-label={title}>
      <div className="flex items-center justify-between border-b border-hairline px-4 py-3">
        <h2 className="text-section-title">{title}</h2>
        {onClose && (
          <button
            onClick={onClose}
            aria-label="Close inspector"
            className="text-mute hover:text-ink"
          >
            [x]
          </button>
        )}
      </div>
      <div className="flex-1 overflow-y-auto p-4 scrollbar-hairline">{children}</div>
    </aside>
  )
}
