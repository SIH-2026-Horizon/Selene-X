import { seleneApi, type ApiRequestOptions } from '@/services/api/client'
import type { ApiProduct, CursorPage } from '@/services/api/contracts'
import type { Product } from '@/types/product'

export interface CatalogFilters {
  validationState?: string
  query?: string
  cursor?: string
  limit?: number
}

export interface ProductPage {
  items: Product[]
  nextCursor: string | null
}

export function productFromApi(product: ApiProduct): Product {
  return {
    id: product.id,
    productIdentity: product.product_identity,
    payloadType: product.payload_type,
    payloadMetadata: product.payload_metadata,
    validationState: product.validation_state,
    validationDetails: product.validation_details,
    manifestSha256: product.manifest_sha256,
    quarantineReason: product.quarantine_reason,
    footprintGeojson: product.footprint_geojson,
    footprintCrs: product.footprint_crs,
    footprintSrid: product.footprint_srid,
    createdAt: product.created_at,
  }
}

export const catalogRepository = {
  async listProducts(filters: CatalogFilters = {}, options?: ApiRequestOptions): Promise<ProductPage> {
    const page = await seleneApi.get<CursorPage<ApiProduct>>('products', {
      ...options,
      query: {
        cursor: filters.cursor,
        limit: filters.limit ?? 50,
        validation_state: filters.validationState,
        query: filters.query,
      },
    })
    return {
      items: page.items.map(productFromApi),
      nextCursor: page.next_cursor,
    }
  },

  async getProduct(id: string, options?: ApiRequestOptions): Promise<Product> {
    return productFromApi(await seleneApi.get<ApiProduct>(`products/${encodeURIComponent(id)}`, options))
  },

  /**
   * A deliberately bounded first page for the command palette.  Further
   * catalog browsing remains cursor based; this never walks the database in
   * the browser to construct a search result.
   */
  async searchProducts(query: string, options?: ApiRequestOptions): Promise<ProductPage> {
    return this.listProducts({ query, limit: 10 }, options)
  },
}
