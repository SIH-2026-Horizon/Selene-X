import type { ReactNode } from 'react'
import { AsciiStatus } from './AsciiStatus'

interface ErrorStateProps {
  code: string
  message: string
  detail?: ReactNode
  actions?: ReactNode
}

export function ErrorState({ code, message, detail, actions }: ErrorStateProps) {
  return (
    <div role="alert" className="border-l-2 border-danger bg-surface-soft p-4">
      <div className="flex items-center gap-2">
        <AsciiStatus marker="bang" tone="danger" />
        <span className="font-mono text-caption font-semibold text-danger">{code}</span>
      </div>
      <p className="mt-2 text-caption text-body">{message}</p>
      {detail && <div className="mt-2 text-caption text-mute">{detail}</div>}
      {actions && <div className="mt-3 flex flex-wrap gap-2">{actions}</div>}
    </div>
  )
}
