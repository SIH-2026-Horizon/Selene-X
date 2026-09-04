import { MemoryRouter } from 'react-router-dom'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { RegistrationJob } from '@/types/job'

const hooks = vi.hoisted(() => ({
  usePersistedRunSummary: vi.fn(),
  usePersistedAuditActivity: vi.fn(),
  usePlatformStatus: vi.fn(),
}))

vi.mock('@/features/jobs/usePersistedRunSummary', () => ({ usePersistedRunSummary: hooks.usePersistedRunSummary }))
vi.mock('@/features/audit/usePersistedAuditActivity', () => ({ usePersistedAuditActivity: hooks.usePersistedAuditActivity }))
vi.mock('@/features/platform/usePlatformStatus', () => ({ usePlatformStatus: hooks.usePlatformStatus }))

import { SideNavigation } from '@/components/shell/SideNavigation'
import { AdminRoute } from './admin/AdminRoute'
import { AuditRoute } from './audit/AuditRoute'
import { CampaignsRoute } from './campaigns/CampaignsRoute'
import { ModelsRoute } from './models/ModelsRoute'
import { ParametersRoute } from './parameters/ParametersRoute'

const persistedRun: RegistrationJob = {
  id: '00000000-0000-4000-8000-000000000001',
  sourceProductId: '00000000-0000-4000-8000-000000000011',
  referenceProductId: '00000000-0000-4000-8000-000000000012',
  parameterManifest: { resampling: 'cubic', grid_spacing_m: 5 },
  parameterManifestAvailable: true,
  parametersSha256: 'a'.repeat(64),
  algorithmVersions: { registration_engine: '3.2.1' },
  modelVersions: { tie_point_ranker: '1.4.0' },
  state: 'succeeded',
  stateVersion: 2,
  eventSequence: 2,
  computedVerdict: 'accepted',
  effectiveDisposition: 'accepted',
  codeRevision: '9f2a8d1',
  environmentFingerprint: 'container:sha256:example',
  createdAt: '2026-08-30T00:00:00Z',
  updatedAt: '2026-08-30T00:00:02Z',
}

describe('persisted navigation routes', () => {
  beforeEach(() => {
    hooks.usePersistedRunSummary.mockReturnValue({ data: { items: [persistedRun], nextCursor: null }, isLoading: false, error: null })
    hooks.usePersistedAuditActivity.mockReturnValue({
      data: [{
        kind: 'event',
        id: '00000000-0000-4000-8000-000000000101',
        runId: persistedRun.id,
        recordedAt: '2026-08-30T00:00:01Z',
        actorSubjectId: null,
        event: {
          id: '00000000-0000-4000-8000-000000000101',
          run_id: persistedRun.id,
          actor_subject_id: null,
          event_type: 'run_created',
          execution_state: 'created',
          sequence: 1,
          event_document: { state: 'created' },
          recorded_at: '2026-08-30T00:00:01Z',
        },
      }],
      isLoading: false,
      error: null,
      hasRuns: true,
      hasMore: false,
      loadedRunCount: 1,
    })
    hooks.usePlatformStatus.mockReturnValue({
      data: {
        liveness: { endpoint: '/healthz', status: 200, ok: true, message: 'Available' },
        readiness: { endpoint: '/readyz', status: 200, ok: true, message: 'Available' },
        version: { endpoint: '/api/v1/version', status: 200, ok: true, message: 'Available' },
        serviceVersion: { service: 'selene-service', version: '1.2.3', environment: 'local' },
      },
      isLoading: false,
      isFetching: false,
      error: null,
      refetch: vi.fn(),
    })
  })

  it('renders parameter manifests and model versions from persisted run definitions', () => {
    const { rerender } = render(<MemoryRouter><ParametersRoute /></MemoryRouter>)

    expect(screen.getByText('Persisted parameters')).toBeInTheDocument()
    expect(screen.getByText('View persisted manifest')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: persistedRun.id })).toHaveAttribute('href', `/jobs/${persistedRun.id}`)

    rerender(<MemoryRouter><ModelsRoute /></MemoryRouter>)
    expect(screen.getByText('tie_point_ranker')).toBeInTheDocument()
    expect(screen.getByText('"1.4.0"')).toBeInTheDocument()
  })

  it('renders actual run event activity and live platform probes', () => {
    const { rerender } = render(<MemoryRouter><AuditRoute /></MemoryRouter>)

    expect(screen.getByText('Persisted run activity')).toBeInTheDocument()
    expect(screen.getByText('run_created · created')).toBeInTheDocument()
    expect(screen.getByText('Event document')).toBeInTheDocument()

    rerender(<MemoryRouter><AdminRoute /></MemoryRouter>)
    expect(screen.getByText('Process liveness')).toBeInTheDocument()
    expect(screen.getAllByText('AVAILABLE')).toHaveLength(3)
    expect(screen.getByText('1.2.3')).toBeInTheDocument()
  })

  it('shows campaigns in primary navigation while retaining a truthful unavailable state', () => {
    const { rerender } = render(<MemoryRouter><SideNavigation /></MemoryRouter>)

    expect(screen.getByRole('link', { name: 'Campaigns' })).toHaveAttribute('href', '/campaigns')

    rerender(<MemoryRouter><CampaignsRoute /></MemoryRouter>)
    expect(screen.getByText('CAMPAIGN RECORDS UNAVAILABLE')).toBeInTheDocument()
  })
})
