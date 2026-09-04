import { useQuery } from '@tanstack/react-query'
import { jobsRepository } from '@/repositories/jobsRepository'
import type { RegistrationJob } from '@/types/job'

export interface PersistedRunSummary {
  items: RegistrationJob[]
  nextCursor: string | null
}

/**
 * A deliberately bounded persisted-run summary for non-Jobs routes.
 *
 * The interactive Jobs page is the place to traverse further cursor pages.
 * Summary routes must never silently fetch an unbounded database collection.
 */
async function listPersistedRunSummary(signal?: AbortSignal): Promise<PersistedRunSummary> {
  return jobsRepository.listJobs({ limit: 100 }, { signal })
}

export function usePersistedRunSummary() {
  return useQuery({
    queryKey: ['jobs', 'persisted-summary'],
    queryFn: ({ signal }) => listPersistedRunSummary(signal),
  })
}
