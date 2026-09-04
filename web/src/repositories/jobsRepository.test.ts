import { describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))

vi.mock('@/services/api/client', () => ({
  seleneApi: api,
}))

import { jobsRepository } from './jobsRepository'

const run = {
  id: '00000000-0000-4000-8000-000000000001',
  owner_subject_id: '00000000-0000-4000-8000-000000000002',
  source_product_id: '00000000-0000-4000-8000-000000000003',
  reference_product_id: '00000000-0000-4000-8000-000000000004',
  parameter_manifest: null,
  parameter_manifest_available: false,
  parameters_sha256: 'a'.repeat(64),
  algorithm_versions: {},
  model_versions: {},
  execution_state: 'created',
  state_version: 0,
  event_sequence: 1,
  computed_verdict: null,
  effective_disposition: 'pending',
  code_revision: 'operator-revision',
  environment_fingerprint: 'operator-environment',
  created_at: '2026-08-30T00:00:00Z',
  updated_at: '2026-08-30T00:00:00Z',
}

describe('jobsRepository detail paging', () => {
  it('loads one bounded page per persisted child collection', async () => {
    api.get.mockImplementation((path: string) => {
      if (path === `runs/${run.id}`) return Promise.resolve(run)
      return Promise.resolve({ items: [], next_cursor: 'next-persisted-page' })
    })

    const detail = await jobsRepository.getJobDetail(run.id)

    expect(api.get).toHaveBeenCalledTimes(6)
    expect(detail.collectionCursors).toEqual({
      stages: 'next-persisted-page',
      artifacts: 'next-persisted-page',
      metrics: 'next-persisted-page',
      events: 'next-persisted-page',
      reviews: 'next-persisted-page',
    })
    for (const [path, options] of api.get.mock.calls.filter(([path]) => path !== `runs/${run.id}`)) {
      expect(path).toMatch(/^runs\/00000000-0000-4000-8000-000000000001\//)
      expect(options).toMatchObject({ query: { cursor: null, limit: 50 } })
    }
  })

  it('propagates one stable command key to every persisted mutation endpoint', async () => {
    const idempotencyKey = 'c2b90fef-c4a1-4ec8-af03-19f7de7c99cc'
    api.post.mockResolvedValue(run)

    await jobsRepository.createJob({
      sourceProductId: run.source_product_id,
      referenceProductId: run.reference_product_id,
      parameterManifest: {},
      algorithmVersions: {},
      modelVersions: {},
      codeRevision: run.code_revision,
      environmentFingerprint: run.environment_fingerprint,
    }, idempotencyKey)
    await jobsRepository.cancelJob(run.id, idempotencyKey)
    await jobsRepository.submitReviewDecision(run.id, { decision: 'accepted', reasonCode: 'persisted-review' }, idempotencyKey)

    expect(api.post).toHaveBeenNthCalledWith(1, 'runs', expect.any(Object), { idempotencyKey })
    expect(api.post).toHaveBeenNthCalledWith(2, `runs/${run.id}/cancel`, {}, { idempotencyKey })
    expect(api.post).toHaveBeenNthCalledWith(3, `runs/${run.id}/reviews`, expect.any(Object), { idempotencyKey })
  })
})
