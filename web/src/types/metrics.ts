export type MetricStatus = 'measured' | 'target' | 'provisional_target' | 'unavailable'

export interface Metric {
  status: MetricStatus
  value: number | null
  unit?: string
}

export type GateVerdict = 'pass' | 'fail' | 'review'

export interface QualityGate {
  id: string
  label: string
  measured: Metric
  thresholdLabel: string
  verdict: GateVerdict
  profile?: string
}

export type JobVerdictValue = 'PASS' | 'REVIEW' | 'REJECTED' | 'PENDING'

export interface JobMetrics {
  rmseX?: Metric
  rmseY?: Metric
  rmse2d?: Metric
  medianEndpointErrorPx?: Metric
  ce90Px?: Metric
  candidateCount?: Metric
  verifiedInlierCount?: Metric
  inlierRatio?: Metric
  eligibleCellOccupancyPct?: Metric
  overlapAreaKm2?: Metric
  largestEmptyRegionPct?: Metric
  sunlitBothFraction?: Metric
  runtimeSeconds?: Metric
  memoryMb?: Metric
  gates: QualityGate[]
  verdict: JobVerdictValue
}
