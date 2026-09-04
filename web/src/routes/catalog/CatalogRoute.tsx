import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useProduct, useProducts } from '@/features/catalog/useCatalog'
import { LunarMap } from '@/components/map/LunarMap'
import { supportsLunarFootprint } from '@/components/map/footprintLayer'
import { ErrorState } from '@/components/ui/ErrorState'
import { EmptyState } from '@/components/ui/EmptyState'
import { InspectorPanel } from '@/components/ui/InspectorPanel'
import { LoadingState } from '@/components/ui/LoadingState'
import { MetadataGrid } from '@/components/ui/MetadataGrid'
import { SearchInput } from '@/components/ui/SearchInput'
import { Button } from '@/components/ui/Button'
import { isSeleneApiError } from '@/services/api/client'

function textDocument(value: unknown): string {
  return JSON.stringify(value, null, 2)
}

export function CatalogRoute() {
  const { productId } = useParams()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [validationState, setValidationState] = useState('')
  const filters = useMemo(() => ({ query, validationState: validationState || undefined }), [query, validationState])
  const productsQuery = useProducts(filters)
  const selectedQuery = useProduct(productId)
  const selectedProduct = productId ? selectedQuery.data : undefined
  const products = productsQuery.data?.pages.flatMap((page) => page.items) ?? []

  return (
    <div className="grid h-full grid-cols-[minmax(0,1fr)_340px] divide-x divide-hairline">
      <div className="flex min-w-0 flex-col">
        <div className="flex flex-wrap items-center gap-3 border-b border-hairline p-4">
          <SearchInput value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search stored product identity, UUID, or payload type…" />
          <label className="text-caption text-mute">
            Validation state
            <input value={validationState} onChange={(event) => setValidationState(event.target.value)} placeholder="e.g. VALIDATED" className="ml-2 w-36 border border-hairline bg-canvas px-2 py-1.5 text-caption text-ink focus:outline-none" />
          </label>
          {productsQuery.hasNextPage && <span className="text-micro text-mute">More persisted records are available.</span>}
        </div>
        <div className="h-64 shrink-0 border-b border-hairline">
          <LunarMap products={products} selectedProductId={productId} onSelectProduct={(id) => navigate(`/catalog/${id}`)} className="h-full w-full" />
        </div>
        <div className="min-h-0 flex-1 overflow-auto scrollbar-hairline">
          {productsQuery.isLoading && <LoadingState label="Loading persisted products" />}
          {productsQuery.error && <div className="p-6"><ApiError error={productsQuery.error} /></div>}
          {!productsQuery.isLoading && !productsQuery.error && products.length === 0 && <div className="p-6"><EmptyState title="NO PERSISTED PRODUCTS" description="No loaded product page contains a record matching these stored-field filters." /></div>}
          {products.length > 0 && (
            <table className="w-full min-w-[760px] border-collapse text-caption">
              <thead className="sticky top-0 bg-surface-soft">
                <tr>{['PRODUCT UUID', 'IDENTITY', 'PAYLOAD TYPE', 'VALIDATION', 'CREATED'].map((heading) => <th key={heading} className="border-b border-hairline px-3 py-2 text-left text-micro font-medium uppercase tracking-wide text-mute">{heading}</th>)}</tr>
              </thead>
              <tbody>
                {products.map((product) => (
                  <tr key={product.id} className={product.id === productId ? 'bg-surface-card' : 'border-b border-hairline hover:bg-surface-soft'}>
                    <td className="px-3 py-2 font-medium"><Link to={`/catalog/${product.id}`} className="text-accent hover:underline">{product.id}</Link></td>
                    <td className="px-3 py-2">{product.productIdentity}</td>
                    <td className="px-3 py-2">{product.payloadType}</td>
                    <td className="px-3 py-2">{product.validationState}</td>
                    <td className="px-3 py-2 tabular-nums text-mute">{new Date(product.createdAt).toISOString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {productsQuery.hasNextPage && <div className="p-4"><Button variant="secondary" onClick={() => productsQuery.fetchNextPage()} disabled={productsQuery.isFetchingNextPage}>{productsQuery.isFetchingNextPage ? 'Loading persisted products…' : 'Load more persisted products'}</Button></div>}
        </div>
      </div>
      <aside className="min-w-0 overflow-y-auto p-4 scrollbar-hairline">
        {!productId && <EmptyState title="SELECT A PRODUCT" description="Inspect only persisted product metadata and footprint provenance." />}
        {selectedQuery.isLoading && <LoadingState label="Loading product" />}
        {selectedQuery.error && <ApiError error={selectedQuery.error} />}
        {selectedProduct && (
          <InspectorPanel title="PERSISTED PRODUCT" onClose={() => navigate('/catalog')}>
            <div className="break-all text-section-title">{selectedProduct.productIdentity}</div>
            <div className="mt-4"><MetadataGrid columns={1} entries={[
              { label: 'UUID', value: selectedProduct.id },
              { label: 'Payload type', value: selectedProduct.payloadType },
              { label: 'Validation state', value: selectedProduct.validationState },
              { label: 'Manifest SHA-256', value: selectedProduct.manifestSha256 },
              { label: 'Footprint CRS', value: selectedProduct.footprintCrs ?? 'N/A / no persisted footprint' },
              { label: 'Footprint map rendering', value: selectedProduct.footprintGeojson ? (supportsLunarFootprint(selectedProduct) ? 'Supported plate-carrée footprint' : 'N/A / persisted CRS is not supported by this map') : 'N/A / no persisted footprint' },
              { label: 'Quarantine reason', value: selectedProduct.quarantineReason ?? 'N/A' },
              { label: 'Created', value: new Date(selectedProduct.createdAt).toISOString() },
            ]} /></div>
            <details className="mt-4 border-t border-hairline pt-3"><summary className="cursor-pointer text-caption text-accent">Payload metadata (persisted)</summary><pre className="mt-2 overflow-auto whitespace-pre-wrap break-words border border-hairline p-2 text-micro text-mute">{textDocument(selectedProduct.payloadMetadata)}</pre></details>
            <details className="mt-3"><summary className="cursor-pointer text-caption text-accent">Validation details (persisted)</summary><pre className="mt-2 overflow-auto whitespace-pre-wrap break-words border border-hairline p-2 text-micro text-mute">{textDocument(selectedProduct.validationDetails)}</pre></details>
            <div className="mt-4 border-t border-hairline pt-3"><Button variant="primary" onClick={() => navigate(`/register?source=${selectedProduct.id}`)}> [+] Register with another persisted product</Button></div>
          </InspectorPanel>
        )}
      </aside>
    </div>
  )
}

function ApiError({ error }: { error: unknown }) {
  return isSeleneApiError(error) ? <ErrorState code={error.code} message={error.message} /> : <ErrorState code="REQUEST_FAILED" message="The persisted product request could not be completed." />
}
