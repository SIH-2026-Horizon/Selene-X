import type { ReactNode } from 'react'
import { AsciiStatus } from './AsciiStatus'

interface EmptyStateProps {
  title: string
  description?: ReactNode
  actions?: ReactNode
}

export function EmptyState({ title, description, actions }: EmptyStateProps) {
  return (
    <div className="border border-hairline p-8 text-center">
      <div className="flex items-center justify-center gap-2 text-section-title">
        <AsciiStatus marker="cross" tone="muted" />
        <span>{title}</span>
      </div>
      {description && <p className="mx-auto mt-3 max-w-md text-caption text-mute">{description}</p>}
      {actions && <div className="mt-4 flex justify-center gap-2">{actions}</div>}
    </div>
  )
}
