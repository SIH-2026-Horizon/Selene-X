import { afterEach, describe, expect, it, vi } from 'vitest'
import { catalogRepository } from './catalogRepository'

afterEach(() => vi.unstubAllGlobals())

describe('catalogRepository', () => {
  it('serializes cursor and validation filters and preserves absent stored fields', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      items: [{
        id: 'b6c6e9f3-3d1c-4f32-b4e8-9de8af909155', owner_subject_id: '1ecfd1f7-b7f0-475f-95e3-b915f6fdc955', product_identity: 'actual-product', payload_type: 'OHRC', payload_metadata: {}, validation_state: 'VALIDATED', validation_details: {}, manifest_sha256: 'a'.repeat(64), quarantine_reason: null, footprint_geojson: null, footprint_crs: null, footprint_srid: null, created_at: '2026-08-30T00:00:00Z',
      }], next_cursor: 'next-page',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    const page = await catalogRepository.listProducts({ cursor: 'prior-page', validationState: 'VALIDATED', query: 'actual' })
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/v1/products?cursor=prior-page&limit=50&validation_state=VALIDATED&query=actual')
    expect(page).toEqual(expect.objectContaining({ nextCursor: 'next-page' }))
    expect(page.items[0]).toMatchObject({ productIdentity: 'actual-product', footprintGeojson: null, footprintCrs: null })
  })

  it('uses one bounded server-side page for a command search', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [], next_cursor: 'later-results' }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(catalogRepository.searchProducts('match')).resolves.toEqual({ items: [], nextCursor: 'later-results' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/v1/products?limit=10&query=match')
  })

  it('exposes the API error code and message without falling back to client data', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: 'PRODUCT_NOT_FOUND', message: 'No persisted product.' } }), { status: 404, headers: { 'Content-Type': 'application/json' } })))
    await expect(catalogRepository.getProduct('missing')).rejects.toMatchObject({ code: 'PRODUCT_NOT_FOUND', message: 'No persisted product.', status: 404 })
  })
})
