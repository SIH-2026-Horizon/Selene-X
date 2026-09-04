import clsx from 'clsx'

export type AsciiMarkerKind = 'plus' | 'minus' | 'cross' | 'bang' | 'check' | 'arrow' | 'question' | 'dot' | 'bullet'

const MARKERS: Record<AsciiMarkerKind, string> = {
  plus: '[+]',
  minus: '[-]',
  cross: '[x]',
  bang: '[!]',
  check: '[✓]',
  arrow: '[→]',
  question: '[?]',
  dot: '·',
  bullet: '●',
}

const TONE_CLASS = {
  neutral: 'text-ink',
  muted: 'text-mute',
  info: 'text-accent',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
} as const

export type AsciiTone = keyof typeof TONE_CLASS

interface AsciiStatusProps {
  marker: AsciiMarkerKind
  tone?: AsciiTone
  className?: string
}

export function AsciiStatus({ marker, tone = 'neutral', className }: AsciiStatusProps) {
  return (
    <span aria-hidden="true" className={clsx('inline-block font-mono tabular-nums', TONE_CLASS[tone], className)}>
      {MARKERS[marker]}
    </span>
  )
}
