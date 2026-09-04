import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { SessionUser } from '@/repositories/authRepository'
import type { RegistrationJobDetail } from '@/types/job'

const hooks = vi.hoisted(() => ({ useJobDetail: vi.fn(), useSubmitReviewDecision: vi.fn() }))

vi.mock('@/features/jobs/useJobs', () => ({ useJobDetail: hooks.useJobDetail }))
vi.mock('@/features/review/useSubmitReviewDecision', () => ({ useSubmitReviewDecision: hooks.useSubmitReviewDecision }))

import { ReviewRoute } from './ReviewRoute'

afterEach(() => vi.restoreAllMocks())

const runId = '00000000-0000-4000-8000-000000000001'

const unfinishedRun: RegistrationJobDetail = {
  id: runId,
  sourceProductId: '00000000-0000-4000-8000-000000000011',
  referenceProductId: '00000000-0000-4000-8000-000000000012',
  parameterManifest: null,
  parameterManifestAvailable: false,
  parametersSha256: 'a'.repeat(64),
  algorithmVersions: {},
  modelVersions: {},
  state: 'created',
  stateVersion: 0,
  eventSequence: 1,
  computedVerdict: null,
  effectiveDisposition: 'pending',
  codeRevision: 'operator-revision',
  environmentFingerprint: 'operator-environment',
  createdAt: '2026-08-30T00:00:00Z',
  updatedAt: '2026-08-30T00:00:00Z',
  stages: [],
  artifacts: [],
  metrics: [],
  events: [],
  reviews: [],
  collectionCursors: { stages: null, artifacts: null, metrics: null, events: null, reviews: null },
}

const eligibleRun: RegistrationJobDetail = {
  ...unfinishedRun,
  state: 'succeeded',
  computedVerdict: 'pass',
  effectiveDisposition: 'accepted',
}

/**
 * ReviewRoute reads the session via useRouteSession() (React Router's Outlet
 * context), the same way AppShell provides it in the real app — not a second
 * useSession() query. Route through a parent <Outlet context={sessionUser}>
 * so the component under test sees the same context shape it does in
 * production, rather than mocking authRepository.getSession directly.
 */
function renderReviewRoute(sessionUser: SessionUser | undefined) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/jobs/${runId}/review`]}>
        <Routes>
          <Route element={<Outlet context={sessionUser} />}>
            <Route path="/jobs/:id/review" element={<ReviewRoute />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ReviewRoute scientific eligibility', () => {
  it('does not offer a review decision before a final persisted scientific result', () => {
    hooks.useJobDetail.mockReturnValue({ data: unfinishedRun, isLoading: false, error: null })
    hooks.useSubmitReviewDecision.mockReturnValue({ mutate: vi.fn(), isPending: false, error: null })

    renderReviewRoute(undefined)

    expect(screen.getByText(/Review is unavailable until this run is/)).toBeInTheDocument()
    expect(screen.getByPlaceholderText('Reason code')).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Accept' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled()
  })
})

describe('ReviewRoute role gating', () => {
  it('disables Accept/Reject for a logged-in Analyst even on an eligible run', () => {
    hooks.useJobDetail.mockReturnValue({ data: eligibleRun, isLoading: false, error: null })
    hooks.useSubmitReviewDecision.mockReturnValue({ mutate: vi.fn(), isPending: false, error: null })

    renderReviewRoute({ username: 'a', displayName: 'A', role: 'analyst' })

    expect(screen.getByText(/reviewer or admin role is required/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Accept' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled()
  })

  it('leaves an eligible run reviewable for a Reviewer', () => {
    hooks.useJobDetail.mockReturnValue({ data: eligibleRun, isLoading: false, error: null })
    hooks.useSubmitReviewDecision.mockReturnValue({ mutate: vi.fn(), isPending: false, error: null })

    renderReviewRoute({ username: 'r', displayName: 'R', role: 'reviewer' })

    fireEvent.change(screen.getByPlaceholderText('Reason code'), { target: { value: 'looks-good' } })
    fireEvent.change(screen.getByPlaceholderText('Note (required for rejection)'), { target: { value: 'confirmed' } })

    expect(screen.queryByText(/reviewer or admin role is required/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Accept' })).not.toBeDisabled()
    expect(screen.getByRole('button', { name: 'Reject' })).not.toBeDisabled()
  })
})
