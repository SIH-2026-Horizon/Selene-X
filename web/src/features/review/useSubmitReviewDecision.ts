import { useMutation, useQueryClient } from '@tanstack/react-query'
import { jobsRepository } from '@/repositories/jobsRepository'

export interface SubmitReviewCommand {
  decision: 'accepted' | 'rejected'
  reasonCode: string
  note?: string
  idempotencyKey: string
}

export function useSubmitReviewDecision(jobId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ idempotencyKey, ...decision }: SubmitReviewCommand) => jobsRepository.submitReviewDecision(jobId, decision, idempotencyKey),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['job', jobId] })
      queryClient.invalidateQueries({ queryKey: ['job', jobId, 'detail'] })
      queryClient.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
}
