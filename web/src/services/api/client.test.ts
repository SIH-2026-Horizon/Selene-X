import { afterEach, describe, expect, it, vi } from 'vitest'
import { seleneApi } from './client'

describe('SELENE API mutation client', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('sends the caller-owned Idempotency-Key header unchanged', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await seleneApi.post('runs', { persisted: 'definition' }, { idempotencyKey: 'c2b90fef-c4a1-4ec8-af03-19f7de7c99cc' })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Idempotency-Key': 'c2b90fef-c4a1-4ec8-af03-19f7de7c99cc',
      },
    })
  })
})
