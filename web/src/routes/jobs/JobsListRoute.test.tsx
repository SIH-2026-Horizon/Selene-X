import { MemoryRouter } from 'react-router-dom'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { RegistrationJob } from '@/types/job'

const hooks = vi.hoisted(() => ({ useJobs: vi.fn() }))

vi.mock('@/features/jobs/useJobs', () => ({ useJobs: hooks.useJobs }))

import { JobsListRoute } from './JobsListRoute'

const createdRun: RegistrationJob = {
  id: '00000000-0000-4000-8000-000000000001',
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
  codeRevision: 'revision',
  environmentFingerprint: 'environment',
  createdAt: '2026-08-30T00:00:00Z',
  updatedAt: '2026-08-30T00:00:00Z',
}

const succeededRun: RegistrationJob = {
  ...createdRun,
  id: '00000000-0000-4000-8000-000000000002',
  state: 'succeeded',
  stateVersion: 4,
  eventSequence: 5,
  effectiveDisposition: 'accepted',
}

describe('JobsListRoute API lifecycle rendering', () => {
  beforeEach(() => {
    hooks.useJobs.mockReturnValue({
      data: { pages: [{ items: [createdRun, succeededRun], nextCursor: null }] },
      isLoading: false,
      error: null,
      hasNextPage: false,
    })
  })

  it('renders lowercase API states and filters by the persisted succeeded value', () => {
    render(<MemoryRouter initialEntries={['/jobs?state=succeeded']}><JobsListRoute /></MemoryRouter>)

    expect(screen.getAllByText('SUCCEEDED')).toHaveLength(2)
    expect(screen.getByRole('link', { name: succeededRun.id })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: createdRun.id })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'SUCCEEDED' })).toHaveClass('bg-ink')
  })
})
