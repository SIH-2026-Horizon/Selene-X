import type { ReactNode } from 'react'
import clsx from 'clsx'
import { AsciiStatus, type AsciiMarkerKind, type AsciiTone } from './AsciiStatus'

export type VerdictKind = 'ready' | 'pass' | 'review' | 'rejected' | 'blocked'

const VERDICT_CONFIG: Record<VerdictKind, { marker: AsciiMarkerKind; tone: AsciiTone; border: string }> = {
  ready: { marker: 'check', tone: 'success', border: 'border-success' },
  pass: { marker: 'check', tone: 'success', border: 'border-success' },
  review: { marker: 'bang', tone: 'warning', border: 'border-warning' },
  rejected: { marker: 'cross', tone: 'danger', border: 'border-danger' },
  blocked: { marker: 'cross', tone: 'danger', border: 'border-danger' },
}

interface VerdictBannerProps {
  kind: VerdictKind
  title: string
  description?: ReactNode
  actions?: ReactNode
}

export function VerdictBanner({ kind, title, description, actions }: VerdictBannerProps) {
  const config = VERDICT_CONFIG[kind]
  return (
    <div className={clsx('border-l-2 bg-surface-soft p-4', config.border)}>
      <div className="flex flex-wrap items-center gap-3">
        <AsciiStatus marker={config.marker} tone={config.tone} className="text-body" />
        <span className="text-section-title">{title}</span>
        {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
      </div>
      {description && <div className="mt-2 text-caption text-body">{description}</div>}
    </div>
  )
}
