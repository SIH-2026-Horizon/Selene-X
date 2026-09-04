import { useMutation, useQueryClient } from '@tanstack/react-query'
import { authRepository } from '@/repositories/authRepository'

export function useLogin() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      authRepository.login(username, password),
    onSuccess: (user) => {
      queryClient.setQueryData(['session'], user)
    },
  })
}
