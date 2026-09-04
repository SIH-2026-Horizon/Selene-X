import { seleneApi, type ApiRequestOptions } from '@/services/api/client'
import type { ApiReview, ApiRunEvent, CursorPage } from '@/services/api/contracts'

export type PersistedActivity =
  | { kind: 'event'; id: string; runId: string; recordedAt: string; actorSubjectId: string | null; event: ApiRunEvent }
  | { kind: 'review'; id: string; runId: string; recordedAt: string; actorSubjectId: string; review: ApiReview }

export interface PersistedActivityPage {
  items: PersistedActivity[]
  hasMore: boolean
}

export const auditRepository = {
  /**
   * Returns only the initial event and review pages for one run. The run
   * detail page exposes explicit cursor controls for complete inspection.
   */
  async listRunActivity(runId: string, options?: ApiRequestOptions): Promise<PersistedActivityPage> {
    const encodedRunId = encodeURIComponent(runId)
    const [eventPage, reviewPage] = await Promise.all([
      seleneApi.get<CursorPage<ApiRunEvent>>(`runs/${encodedRunId}/events`, { ...options, query: { limit: 50 } }),
      seleneApi.get<CursorPage<ApiReview>>(`runs/${encodedRunId}/reviews`, { ...options, query: { limit: 50 } }),
    ])

    return {
      items: [
        ...eventPage.items.map((event): PersistedActivity => ({
          kind: 'event',
          id: event.id,
          runId,
          recordedAt: event.recorded_at,
          actorSubjectId: event.actor_subject_id,
          event,
        })),
        ...reviewPage.items.map((review): PersistedActivity => ({
          kind: 'review',
          id: review.id,
          runId,
          recordedAt: review.recorded_at,
          actorSubjectId: review.actor_subject_id,
          review,
        })),
      ],
      hasMore: Boolean(eventPage.next_cursor || reviewPage.next_cursor),
    }
  },
}
