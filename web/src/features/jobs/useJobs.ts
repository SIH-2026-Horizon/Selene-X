import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { jobsRepository } from '@/repositories/jobsRepository'

export function useJobs() {
  return useInfiniteQuery({
    queryKey: ['jobs'],
    initialPageParam: null as string | null,
    queryFn: ({ signal, pageParam }) => jobsRepository.listJobs({ cursor: pageParam }, { signal }),
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  })
}

export function useJob(id: string | undefined) {
  return useQuery({
    queryKey: ['job', id],
    queryFn: ({ signal }) => jobsRepository.getJob(id as string, { signal }),
    enabled: Boolean(id),
  })
}

export function useJobDetail(id: string | undefined) {
  return useQuery({
    queryKey: ['job', id, 'detail'],
    queryFn: ({ signal }) => jobsRepository.getJobDetail(id as string, { signal }),
    enabled: Boolean(id),
  })
}
