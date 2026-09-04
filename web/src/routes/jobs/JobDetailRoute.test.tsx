import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { RegistrationJobDetail } from '@/types/job'

const hooks = vi.hoisted(() => ({ useJobDetail: vi.fn(), useJobLiveUpdates: vi.fn() }))

vi.mock('@/features/jobs/useJobs', () => ({ useJobDetail: hooks.useJobDetail }))
vi.mock('@/features/jobs/useJobLiveUpdates', () => ({ useJobLiveUpdates: hooks.useJobLiveUpdates }))

import { JobDetailRoute } from './JobDetailRoute'

const runId = '00000000-0000-4000-8000-000000000001'

function persistedRun(state: 'created' | 'succeeded'): RegistrationJobDetail {
  return {
    id: runId,
    sourceProductId: '00000000-0000-4000-8000-000000000011',
    referenceProductId: '00000000-0000-4000-8000-000000000012',
    parameterManifest: null,
    parameterManifestAvailable: false,
    parametersSha256: 'a'.repeat(64),
    algorithmVersions: {},
    modelVersions: {},
    state,
    stateVersion: state === 'created' ? 0 : 4,
    eventSequence: state === 'created' ? 1 : 5,
    computedVerdict: null,
    effectiveDisposition: state === 'created' ? 'pending' : 'accepted',
    codeRevision: 'revision',
    environmentFingerprint: 'environment',
    createdAt: '2026-08-30T00:00:00Z',
    updatedAt: '2026-08-30T00:00:00Z',
    stages: [],
    artifacts: [],
    metrics: [],
    events: [],
    reviews: [],
    collectionCursors: { stages: null, artifacts: null, metrics: null, events: null, reviews: null },
  }
}

function renderRoute() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/jobs/${runId}`]}>
        <Routes><Route path="/jobs/:id" element={<JobDetailRoute />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('JobDetailRoute API lifecycle actions', () => {
  beforeEach(() => {
    hooks.useJobLiveUpdates.mockClear()
  })

  it('allows cancellation and polling for an API created run', () => {
    hooks.useJobDetail.mockReturnValue({ data: persistedRun('created'), isLoading: false, error: null })
    renderRoute()

    expect(screen.getByText('CREATED')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cancel persisted run' })).toBeInTheDocument()
    expect(screen.getByText(/Persisted event log \(polling\)/)).toBeInTheDocument()
    expect(hooks.useJobLiveUpdates).toHaveBeenLastCalledWith(runId, 'created')
  })

  it('does not offer cancellation or polling after an API succeeded run', () => {
    hooks.useJobDetail.mockReturnValue({ data: persistedRun('succeeded'), isLoading: false, error: null })
    renderRoute()

    expect(screen.getByText('SUCCEEDED')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Cancel persisted run' })).not.toBeInTheDocument()
    expect(screen.queryByText(/Persisted event log \(polling\)/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Review persisted records' })).toBeInTheDocument()
    expect(hooks.useJobLiveUpdates).toHaveBeenLastCalledWith(runId, 'succeeded')
  })
})
