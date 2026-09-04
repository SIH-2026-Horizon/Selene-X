import { useMutation, useQueryClient } from '@tanstack/react-query'
import { authRepository } from '@/repositories/authRepository'

export function useLogout() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => authRepository.logout(),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ['session'] })
    },
  })
}
