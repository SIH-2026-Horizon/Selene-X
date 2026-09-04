import { MemoryRouter } from 'react-router-dom'
import { render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { RegistrationJob } from '@/types/job'

const hooks = vi.hoisted(() => ({ useJobs: vi.fn() }))

vi.mock('@/features/jobs/useJobs', () => ({ useJobs: hooks.useJobs }))

import { OverviewRoute } from './OverviewRoute'

const apiRuns: RegistrationJob[] = ['created', 'succeeded'].map((state, index) => ({
  id: `00000000-0000-4000-8000-00000000000${index + 1}`,
  sourceProductId: '00000000-0000-4000-8000-000000000011',
  referenceProductId: '00000000-0000-4000-8000-000000000012',
  parameterManifest: null,
  parameterManifestAvailable: false,
  parametersSha256: 'a'.repeat(64),
  algorithmVersions: {},
  modelVersions: {},
  state,
  stateVersion: index,
  eventSequence: index + 1,
  computedVerdict: null,
  effectiveDisposition: state === 'succeeded' ? 'accepted' : 'pending',
  codeRevision: 'revision',
  environmentFingerprint: 'environment',
  createdAt: '2026-08-30T00:00:00Z',
  updatedAt: `2026-08-30T00:00:0${index}Z`,
}))

describe('OverviewRoute API lifecycle counts', () => {
  beforeEach(() => {
    hooks.useJobs.mockReturnValue({
      data: { pages: [{ items: apiRuns, nextCursor: null }] },
      isLoading: false,
      error: null,
      hasNextPage: false,
    })
  })

  it('counts created as active and succeeded as terminal while rendering both states', () => {
    render(<MemoryRouter><OverviewRoute /></MemoryRouter>)

    expect(within(screen.getByText('ACTIVE (LOADED)').parentElement!).getByText('1')).toBeInTheDocument()
    expect(within(screen.getByText('SUCCEEDED (LOADED)').parentElement!).getByText('1')).toBeInTheDocument()
    expect(screen.getByText('CREATED')).toBeInTheDocument()
    expect(screen.getByText('SUCCEEDED')).toBeInTheDocument()
  })
})
