import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { craterRepository } from '@/repositories/craterRepository'
import { knowledgeRepository } from '@/repositories/knowledgeRepository'

export function useCraters() {
  return useQuery({
    queryKey: ['craters'],
    queryFn: ({ signal }) => craterRepository.listCraters({ signal }),
  })
}

export function useCraterNeighbours(craterId: string | null | undefined) {
  return useInfiniteQuery({
    queryKey: ['crater', craterId, 'neighbours'],
    initialPageParam: null as string | null,
    queryFn: ({ signal, pageParam }) => knowledgeRepository.getNeighbours(craterId as string, { cursor: pageParam }, { signal }),
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    enabled: Boolean(craterId),
  })
}

export function useCrater(craterId: string | null | undefined) {
  return useQuery({
    queryKey: ['crater', craterId],
    queryFn: ({ signal }) => craterRepository.getCrater(craterId as string, { signal }),
    enabled: Boolean(craterId),
  })
}

export function useCraterObservations(craterId: string | null | undefined) {
  return useInfiniteQuery({
    queryKey: ['crater', craterId, 'observations'],
    initialPageParam: null as string | null,
    queryFn: ({ signal, pageParam }) => craterRepository.getObservations(craterId as string, { cursor: pageParam }, { signal }),
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    enabled: Boolean(craterId),
  })
}
