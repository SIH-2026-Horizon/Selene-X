import type { QualityGate } from '@/types/metrics'
import { AsciiStatus } from './AsciiStatus'
import { MetricValue } from './MetricValue'

const VERDICT_CONFIG = {
  pass: { marker: 'check', tone: 'success' },
  fail: { marker: 'cross', tone: 'danger' },
  review: { marker: 'bang', tone: 'warning' },
} as const

interface GateResultProps {
  gate: QualityGate
}

export function GateResult({ gate }: GateResultProps) {
  const config = VERDICT_CONFIG[gate.verdict]
  return (
    <div className="border border-hairline p-3">
      <div className="flex items-center gap-2">
        <AsciiStatus marker={config.marker} tone={config.tone} />
        <span className="text-caption font-medium">{gate.label}</span>
        {gate.profile && <span className="ml-auto text-micro text-mute">PROFILE {gate.profile}</span>}
      </div>
      <div className="mt-2 flex items-baseline justify-between text-caption">
        <span className="text-mute">MEASURED</span>
        <MetricValue metric={gate.measured} />
      </div>
      <div className="mt-1 flex items-baseline justify-between text-caption">
        <span className="text-mute">THRESHOLD</span>
        <span className="text-ink">{gate.thresholdLabel}</span>
      </div>
    </div>
  )
}
