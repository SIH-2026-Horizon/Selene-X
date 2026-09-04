import { afterEach, describe, expect, it, vi } from 'vitest'
import { platformRepository } from './platformRepository'

describe('platformRepository', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('reads only same-origin liveness, readiness, and version endpoints', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'ok' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'ok' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ service: 'selene-service', version: '1.2.3', environment: 'local' }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const status = await platformRepository.getStatus()

    expect(fetchMock.mock.calls.map(([endpoint]) => endpoint)).toEqual(['/healthz', '/readyz', '/api/v1/version'])
    expect(status.liveness.ok).toBe(true)
    expect(status.readiness.ok).toBe(true)
    expect(status.serviceVersion).toEqual({ service: 'selene-service', version: '1.2.3', environment: 'local' })
  })

  it('keeps an unavailable readiness response truthful and does not expose a version as available', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'ok' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: { code: 'service_unavailable', message: 'The service is temporarily unavailable.' } }), { status: 503 }))
      .mockResolvedValueOnce(new Response('', { status: 503, statusText: 'Service Unavailable' }))
    vi.stubGlobal('fetch', fetchMock)

    const status = await platformRepository.getStatus()

    expect(status.readiness).toMatchObject({ endpoint: '/readyz', status: 503, ok: false, message: 'The service is temporarily unavailable.' })
    expect(status.version.ok).toBe(false)
    expect(status.serviceVersion).toBeNull()
  })
})
