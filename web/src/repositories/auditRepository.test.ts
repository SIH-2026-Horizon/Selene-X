import { describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ get: vi.fn() }))

vi.mock('@/services/api/client', () => ({ seleneApi: api }))

import { auditRepository } from './auditRepository'

const runId = '00000000-0000-4000-8000-000000000001'

describe('auditRepository bounded activity', () => {
  it('loads just the initial event and review pages and reports further records', async () => {
    api.get.mockResolvedValueOnce({
      items: [{
        id: '00000000-0000-4000-8000-000000000101', run_id: runId,
        actor_subject_id: null, event_type: 'run_created', execution_state: 'created',
        sequence: 1, event_document: {}, recorded_at: '2026-08-30T00:00:00Z',
      }],
      next_cursor: 'event-next',
    }).mockResolvedValueOnce({ items: [], next_cursor: null })

    const page = await auditRepository.listRunActivity(runId)

    expect(api.get).toHaveBeenCalledTimes(2)
    expect(api.get).toHaveBeenNthCalledWith(1, `runs/${runId}/events`, { query: { limit: 50 } })
    expect(api.get).toHaveBeenNthCalledWith(2, `runs/${runId}/reviews`, { query: { limit: 50 } })
    expect(page.items).toHaveLength(1)
    expect(page.hasMore).toBe(true)
  })
})
