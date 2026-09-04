import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { isJobStateActive, type JobState } from '@/types/job'

/** The API has no SSE transport. Refetch persisted state while the run is active. */
export function useJobLiveUpdates(jobId: string | undefined, state: JobState | undefined) {
  const queryClient = useQueryClient()
  const active = state !== undefined && isJobStateActive(state)

  useEffect(() => {
    if (!jobId || !active) return
    const timer = window.setInterval(() => {
      void queryClient.invalidateQueries({ queryKey: ['job', jobId] })
      void queryClient.invalidateQueries({ queryKey: ['jobs'] })
    }, 5_000)
    return () => window.clearInterval(timer)
  }, [active, jobId, queryClient])
}
