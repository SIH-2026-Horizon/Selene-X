import { useInfiniteQuery } from '@tanstack/react-query'
import { knowledgeRepository } from '@/repositories/knowledgeRepository'
import type { KnowledgeQueryRequest } from '@/types/knowledge'

export function useKnowledgeQuery(request: KnowledgeQueryRequest | null) {
  return useInfiniteQuery({
    queryKey: ['knowledge', 'query', request],
    initialPageParam: null as string | null,
    queryFn: ({ signal, pageParam }) => knowledgeRepository.query({ ...(request as KnowledgeQueryRequest), cursor: pageParam }, { signal }),
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    enabled: request !== null,
  })
}

/** Explicit cursor traversal for one entity's persisted relationship history. */
export function useKnowledgeNeighbours(entityId: string | null) {
  return useInfiniteQuery({
    queryKey: ['knowledge', 'entity-neighbours', entityId],
    initialPageParam: null as string | null,
    queryFn: ({ signal, pageParam }) => knowledgeRepository.getNeighbours(entityId as string, { cursor: pageParam }, { signal }),
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    enabled: entityId !== null,
  })
}
