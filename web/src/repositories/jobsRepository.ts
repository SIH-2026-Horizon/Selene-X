import { seleneApi, type ApiRequestOptions } from '@/services/api/client'
import type { ApiArtifact, ApiMetric, ApiReview, ApiRun, ApiRunEvent, ApiStage, CursorPage, JsonDocument } from '@/services/api/contracts'
import type { RegistrationJob, RegistrationJobDetail } from '@/types/job'
import type { RunDetailCollection, RunDetailCursors } from '@/types/job'

export interface RunFilters {
  executionState?: string
  query?: string
  cursor?: string
  limit?: number
}

export interface RunPage {
  items: RegistrationJob[]
  nextCursor: string | null
}

export interface CreateJobInput {
  sourceProductId: string
  referenceProductId: string
  parameterManifest: JsonDocument
  algorithmVersions: JsonDocument
  modelVersions: JsonDocument
  codeRevision: string
  environmentFingerprint: string
  parametersSha256?: string
}

export function jobFromApi(run: ApiRun): RegistrationJob {
  return {
    id: run.id,
    sourceProductId: run.source_product_id,
    referenceProductId: run.reference_product_id,
    parameterManifest: run.parameter_manifest,
    parameterManifestAvailable: run.parameter_manifest_available,
    parametersSha256: run.parameters_sha256,
    algorithmVersions: run.algorithm_versions,
    modelVersions: run.model_versions,
    state: run.execution_state,
    stateVersion: run.state_version,
    eventSequence: run.event_sequence,
    computedVerdict: run.computed_verdict,
    effectiveDisposition: run.effective_disposition,
    codeRevision: run.code_revision,
    environmentFingerprint: run.environment_fingerprint,
    createdAt: run.created_at,
    updatedAt: run.updated_at,
  }
}

const DETAIL_PAGE_LIMIT = 50

interface RunDetailResourceMap {
  stages: ApiStage
  artifacts: ApiArtifact
  metrics: ApiMetric
  events: ApiRunEvent
  reviews: ApiReview
}

type RunDetailPage<Resource extends RunDetailCollection> = {
  items: RunDetailResourceMap[Resource][]
  nextCursor: string | null
}

async function getDetailPage<Resource extends RunDetailCollection>(
  runId: string,
  resource: Resource,
  cursor: string | null,
  options?: ApiRequestOptions,
): Promise<RunDetailPage<Resource>> {
  const page = await seleneApi.get<CursorPage<RunDetailResourceMap[Resource]>>(
    `runs/${encodeURIComponent(runId)}/${resource}`,
    { ...options, query: { cursor, limit: DETAIL_PAGE_LIMIT } },
  )
  return { items: page.items, nextCursor: page.next_cursor }
}

export const jobsRepository = {
  async listJobs(filters: RunFilters = {}, options?: ApiRequestOptions): Promise<RunPage> {
    const page = await seleneApi.get<CursorPage<ApiRun>>('runs', {
      ...options,
      query: {
        cursor: filters.cursor,
        limit: filters.limit ?? 50,
        execution_state: filters.executionState,
        query: filters.query,
      },
    })
    return { items: page.items.map(jobFromApi), nextCursor: page.next_cursor }
  },

  async getJob(id: string, options?: ApiRequestOptions): Promise<RegistrationJob> {
    return jobFromApi(await seleneApi.get<ApiRun>(`runs/${encodeURIComponent(id)}`, options))
  },

  /** Bounded persisted-field lookup for the command palette. */
  async searchJobs(query: string, options?: ApiRequestOptions): Promise<RunPage> {
    return this.listJobs({ query, limit: 10 }, options)
  },

  async getJobDetail(id: string, options?: ApiRequestOptions): Promise<RegistrationJobDetail> {
    const [run, stages, artifacts, metrics, events, reviews] = await Promise.all([
      this.getJob(id, options),
      getDetailPage(id, 'stages', null, options),
      getDetailPage(id, 'artifacts', null, options),
      getDetailPage(id, 'metrics', null, options),
      getDetailPage(id, 'events', null, options),
      getDetailPage(id, 'reviews', null, options),
    ])
    const collectionCursors: RunDetailCursors = {
      stages: stages.nextCursor,
      artifacts: artifacts.nextCursor,
      metrics: metrics.nextCursor,
      events: events.nextCursor,
      reviews: reviews.nextCursor,
    }
    return {
      ...run,
      stages: stages.items,
      artifacts: artifacts.items,
      metrics: metrics.items,
      events: events.items,
      reviews: reviews.items,
      collectionCursors,
    }
  },

  /** Fetch one explicit additional persisted detail page; callers own loaded scope. */
  getJobDetailCollection<Resource extends RunDetailCollection>(
    id: string,
    resource: Resource,
    cursor: string,
    options?: ApiRequestOptions,
  ): Promise<RunDetailPage<Resource>> {
    return getDetailPage(id, resource, cursor, options)
  },

  async createJob(input: CreateJobInput, idempotencyKey: string, options?: ApiRequestOptions): Promise<RegistrationJob> {
    const response = await seleneApi.post<ApiRun, Record<string, unknown>>(
      'runs',
      {
        source_product_id: input.sourceProductId,
        reference_product_id: input.referenceProductId,
        parameter_manifest: input.parameterManifest,
        parameters_sha256: input.parametersSha256,
        algorithm_versions: input.algorithmVersions,
        model_versions: input.modelVersions,
        code_revision: input.codeRevision,
        environment_fingerprint: input.environmentFingerprint,
      },
      { ...options, idempotencyKey },
    )
    return jobFromApi(response)
  },

  async cancelJob(id: string, idempotencyKey: string, options?: ApiRequestOptions): Promise<RegistrationJob> {
    return jobFromApi(await seleneApi.post<ApiRun, Record<string, never>>(`runs/${encodeURIComponent(id)}/cancel`, {}, { ...options, idempotencyKey }))
  },

  async submitReviewDecision(
    id: string,
    decision: { decision: 'accepted' | 'rejected'; reasonCode: string; note?: string },
    idempotencyKey: string,
    options?: ApiRequestOptions,
  ): Promise<ApiReview> {
    return seleneApi.post<ApiReview, Record<string, unknown>>(
      `runs/${encodeURIComponent(id)}/reviews`,
      { decision: decision.decision, reason_code: decision.reasonCode, note: decision.note?.trim() || undefined },
      { ...options, idempotencyKey },
    )
  },
}
