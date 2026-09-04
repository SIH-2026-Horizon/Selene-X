import { useQuery } from '@tanstack/react-query'
import { auditRepository, type PersistedActivity } from '@/repositories/auditRepository'
import { usePersistedRunSummary } from '@/features/jobs/usePersistedRunSummary'

const AUDIT_RUN_LIMIT = 25

/**
 * There is no global audit endpoint. Build an activity view solely from the
 * append-only events and reviews exposed for each persisted run.
 */
export function usePersistedAuditActivity() {
  const runsQuery = usePersistedRunSummary()
  const runIds = runsQuery.data?.items.slice(0, AUDIT_RUN_LIMIT).map((run) => run.id).sort() ?? []
  const activityQuery = useQuery({
    queryKey: ['audit', 'run-activity', runIds],
    enabled: runsQuery.isSuccess,
    queryFn: async ({ signal }) => {
      const pages = await Promise.all(
        runIds.map((runId) => auditRepository.listRunActivity(runId, { signal })),
      )
      return {
        items: pages.flatMap((page) => page.items).sort((left, right) => right.recordedAt.localeCompare(left.recordedAt)),
        hasMore: pages.some((page) => page.hasMore) || Boolean(runsQuery.data?.nextCursor),
      }
    },
  })

  return {
    data: activityQuery.data?.items as PersistedActivity[] | undefined,
    isLoading: runsQuery.isLoading || activityQuery.isLoading,
    error: runsQuery.error ?? activityQuery.error,
    hasRuns: runIds.length > 0,
    hasMore: activityQuery.data?.hasMore ?? Boolean(runsQuery.data?.nextCursor),
    loadedRunCount: runIds.length,
  }
}
