import { useQuery } from '@tanstack/react-query'
import { platformRepository } from '@/repositories/platformRepository'

export function usePlatformStatus() {
  return useQuery({
    queryKey: ['platform', 'status'],
    queryFn: ({ signal }) => platformRepository.getStatus(signal),
  })
}
