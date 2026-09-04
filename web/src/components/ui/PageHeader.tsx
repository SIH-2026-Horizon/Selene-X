import type { ReactNode } from 'react'

interface PageHeaderProps {
  eyebrow?: string
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
}

export function PageHeader({ eyebrow, title, description, actions }: PageHeaderProps) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4 border-b border-hairline pb-4">
      <div>
        {eyebrow && <div className="text-micro uppercase tracking-wide text-mute">{eyebrow}</div>}
        <h1 className="text-page-title">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-caption text-body">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}
