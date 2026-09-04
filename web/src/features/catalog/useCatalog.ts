import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { catalogRepository, type CatalogFilters } from '@/repositories/catalogRepository'

export function useProducts(filters?: CatalogFilters) {
  return useInfiniteQuery({
    queryKey: ['products', filters],
    initialPageParam: null as string | null,
    queryFn: ({ signal, pageParam }) => catalogRepository.listProducts({ ...filters, cursor: pageParam }, { signal }),
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  })
}

export function useProduct(id: string | undefined) {
  return useQuery({
    queryKey: ['product', id],
    queryFn: ({ signal }) => catalogRepository.getProduct(id as string, { signal }),
    enabled: Boolean(id),
  })
}
