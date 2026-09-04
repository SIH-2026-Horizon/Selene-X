import type { ApiArtifact, ApiMetric, ApiReview, ApiRunEvent, ApiStage, JsonDocument } from '@/services/api/contracts'

/**
 * Execution states persisted by the service. These values intentionally match
 * the database/API contract exactly; they are not presentation labels.
 */
export const RUN_LIFECYCLE_STATES = [
  'created',
  'queued',
  'running',
  'cancelling',
  'cancelled',
  'succeeded',
  'failed',
] as const

export type KnownJobState = typeof RUN_LIFECYCLE_STATES[number]

/**
 * The string extension keeps historic or newly introduced persisted states
 * renderable while callers use the known lifecycle helpers for behaviour.
 */
export type JobState = KnownJobState | (string & {})
export type JobVerdict = string | null

export const RUN_STATE_FILTERS = [
  { value: 'all', label: 'ALL' },
  { value: 'created', label: 'CREATED' },
  { value: 'queued', label: 'QUEUED' },
  { value: 'running', label: 'RUNNING' },
  { value: 'cancelling', label: 'CANCELLING' },
  { value: 'cancelled', label: 'CANCELLED' },
  { value: 'succeeded', label: 'SUCCEEDED' },
  { value: 'failed', label: 'FAILED' },
] as const

export type JobStateFilter = typeof RUN_STATE_FILTERS[number]['value']

export function parseJobStateFilter(value: string | null): JobStateFilter {
  return RUN_STATE_FILTERS.some((filter) => filter.value === value) ? value as JobStateFilter : 'all'
}

/** Runs whose persisted state can still change and should be refreshed. */
export function isJobStateActive(state: JobState): boolean {
  return state === 'created' || state === 'queued' || state === 'running' || state === 'cancelling'
}

/** Cancellation follows the service transition policy, not a UI approximation. */
export function canCancelJob(state: JobState): boolean {
  return state === 'created' || state === 'queued' || state === 'running'
}

export function isJobStateTerminal(state: JobState): boolean {
  return state === 'cancelled' || state === 'succeeded' || state === 'failed'
}

/** A persisted API run. No pipeline status, stage, or measurement is client-generated. */
export interface RegistrationJob {
  id: string
  sourceProductId: string
  referenceProductId: string
  parameterManifest: JsonDocument | null
  parameterManifestAvailable: boolean
  parametersSha256: string
  algorithmVersions: JsonDocument
  modelVersions: JsonDocument
  state: JobState
  stateVersion: number
  eventSequence: number
  computedVerdict: JobVerdict
  effectiveDisposition: string
  codeRevision: string
  environmentFingerprint: string
  createdAt: string
  updatedAt: string
}

export type Stage = ApiStage
export type StageArtifact = ApiArtifact
export type JobMetricReport = ApiMetric
export type JobLogEvent = ApiRunEvent
export type ReviewDecision = ApiReview

export const RUN_DETAIL_COLLECTIONS = ['stages', 'artifacts', 'metrics', 'events', 'reviews'] as const
export type RunDetailCollection = typeof RUN_DETAIL_COLLECTIONS[number]

export type RunDetailCursors = Record<RunDetailCollection, string | null>

export interface RegistrationJobDetail extends RegistrationJob {
  stages: Stage[]
  artifacts: StageArtifact[]
  metrics: JobMetricReport[]
  events: JobLogEvent[]
  reviews: ReviewDecision[]
  /** Cursors for the first persisted page of each independently loaded collection. */
  collectionCursors: RunDetailCursors
}
