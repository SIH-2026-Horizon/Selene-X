import type { ReactNode } from 'react'

interface SectionHeaderProps {
  title: string
  actions?: ReactNode
}

export function SectionHeader({ title, actions }: SectionHeaderProps) {
  return (
    <div className="mb-3 flex items-center justify-between">
      <h2 className="text-section-title">{title}</h2>
      {actions}
    </div>
  )
}
