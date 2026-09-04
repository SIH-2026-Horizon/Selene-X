import type { ReactNode } from 'react'
import type { Metric } from '@/types/metrics'
import { MetricValue } from './MetricValue'

interface MetricRowProps {
  label: string
  metric?: Metric
  value?: ReactNode
  precision?: number
}

export function MetricRow({ label, metric, value, precision }: MetricRowProps) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-hairline py-2 text-caption last:border-b-0">
      <span className="text-mute">{label}</span>
      <span className="font-medium">{value ?? <MetricValue metric={metric} precision={precision} />}</span>
    </div>
  )
}
