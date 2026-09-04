import { useMutation, useQueryClient } from '@tanstack/react-query'
import { authRepository, type UpdateProfileInput } from '@/repositories/authRepository'

/** Persist profile edits and immediately refresh the shell's session identity. */
export function useUpdateProfile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: UpdateProfileInput) => authRepository.updateProfile(input),
    onSuccess: (user) => queryClient.setQueryData(['session'], user),
  })
}
