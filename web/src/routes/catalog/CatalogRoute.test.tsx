import { MemoryRouter } from 'react-router-dom'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SeleneApiError } from '@/services/api/client'

const hooks = vi.hoisted(() => ({ useProducts: vi.fn(), useProduct: vi.fn() }))

vi.mock('@/features/catalog/useCatalog', () => ({ useProducts: hooks.useProducts, useProduct: hooks.useProduct }))
vi.mock('@/components/map/LunarMap', () => ({ LunarMap: () => <div data-testid="lunar-map" /> }))

import { CatalogRoute } from './CatalogRoute'

describe('CatalogRoute persisted empty and error states', () => {
  beforeEach(() => {
    hooks.useProduct.mockReturnValue({ data: undefined, isLoading: false, error: null })
  })

  it('treats an empty database response as a valid live state', () => {
    hooks.useProducts.mockReturnValue({ data: { pages: [{ items: [], nextCursor: null }] }, isLoading: false, error: null, hasNextPage: false })
    render(<MemoryRouter><CatalogRoute /></MemoryRouter>)
    expect(screen.getByText('NO PERSISTED PRODUCTS')).toBeInTheDocument()
  })

  it('renders the API error rather than a local fallback', () => {
    hooks.useProducts.mockReturnValue({ data: undefined, isLoading: false, error: new SeleneApiError({ code: 'DATABASE_UNAVAILABLE', message: 'The persisted catalog is unavailable.', status: 503 }) })
    render(<MemoryRouter><CatalogRoute /></MemoryRouter>)
    expect(screen.getByText('DATABASE_UNAVAILABLE')).toBeInTheDocument()
    expect(screen.getByText('The persisted catalog is unavailable.')).toBeInTheDocument()
  })
})
