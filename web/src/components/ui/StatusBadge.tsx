import clsx from 'clsx'
import { AsciiStatus, type AsciiMarkerKind, type AsciiTone } from './AsciiStatus'

export type StatusKind = string | null | undefined

interface StatusConfig {
  tone: AsciiTone
  marker: AsciiMarkerKind
  label: string
}

const STATUS_CONFIG: Record<string, StatusConfig> = {
  created: { tone: 'muted', marker: 'dot', label: 'CREATED' },
  queued: { tone: 'info', marker: 'arrow', label: 'QUEUED' },
  running: { tone: 'info', marker: 'arrow', label: 'RUNNING' },
  cancelling: { tone: 'warning', marker: 'bang', label: 'CANCELLING' },
  cancelled: { tone: 'muted', marker: 'minus', label: 'CANCELLED' },
  succeeded: { tone: 'success', marker: 'check', label: 'SUCCEEDED' },
  failed: { tone: 'danger', marker: 'cross', label: 'FAILED' },
  pass: { tone: 'success', marker: 'check', label: 'PASS' },
  review: { tone: 'warning', marker: 'bang', label: 'REVIEW' },
  rejected: { tone: 'danger', marker: 'cross', label: 'REJECTED' },
}

function normaliseStatus(status: StatusKind): string {
  return typeof status === 'string' && status.trim() ? status.trim().toLowerCase() : 'unknown'
}

function unknownStatusConfig(status: string): StatusConfig {
  return {
    tone: 'neutral',
    marker: 'dot',
    label: status.replace(/[_-]+/g, ' ').toUpperCase(),
  }
}

interface StatusBadgeProps {
  status: StatusKind
  className?: string
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const normalizedStatus = normaliseStatus(status)
  const config = STATUS_CONFIG[normalizedStatus] ?? unknownStatusConfig(normalizedStatus)
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-caption font-medium',
        'border-hairline',
        normalizedStatus === 'running' && 'motion-status-running',
        className,
      )}
    >
      <AsciiStatus marker={config.marker} tone={config.tone} />
      <span className={clsx({
        'text-success': config.tone === 'success',
        'text-warning': config.tone === 'warning',
        'text-danger': config.tone === 'danger',
        'text-accent': config.tone === 'info',
        'text-mute': config.tone === 'muted',
        'text-ink': config.tone === 'neutral',
      })}>
        {config.label}
      </span>
    </span>
  )
}
