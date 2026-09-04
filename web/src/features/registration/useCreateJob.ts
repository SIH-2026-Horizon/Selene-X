import { useMutation, useQueryClient } from '@tanstack/react-query'
import { jobsRepository, type CreateJobInput } from '@/repositories/jobsRepository'

export interface CreateJobCommand {
  input: CreateJobInput
  idempotencyKey: string
}

export function useCreateJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ input, idempotencyKey }: CreateJobCommand) => jobsRepository.createJob(input, idempotencyKey),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
}
