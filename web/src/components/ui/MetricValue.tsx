import type { Metric } from '@/types/metrics'

interface MetricValueProps {
  metric: Metric | undefined
  precision?: number
}

export function MetricValue({ metric, precision = 2 }: MetricValueProps) {
  if (!metric || metric.status === 'unavailable' || metric.value === null) {
    return <span className="text-ash">N/A</span>
  }

  const formatted =
    Number.isInteger(metric.value) && Math.abs(metric.value) >= 1
      ? metric.value.toString()
      : metric.value.toFixed(precision)

  return (
    <span className="tabular-nums">
      <span className="text-ink">{formatted}</span>
      {metric.unit ? <span className="ml-1 text-mute">{metric.unit}</span> : null}
      {metric.status === 'target' && <span className="ml-1.5 text-micro text-accent">TARGET</span>}
      {metric.status === 'provisional_target' && (
        <span className="ml-1.5 text-micro text-warning">PROVISIONAL TARGET</span>
      )}
    </span>
  )
}
