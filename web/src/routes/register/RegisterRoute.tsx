import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useProducts } from '@/features/catalog/useCatalog'
import { useCreateJob } from '@/features/registration/useCreateJob'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { LoadingState } from '@/components/ui/LoadingState'
import { PageHeader } from '@/components/ui/PageHeader'
import { createIdempotencyKey, isSeleneApiError } from '@/services/api/client'
import type { JsonDocument } from '@/services/api/contracts'

function parseDocument(value: string, label: string, requireEntries = false): JsonDocument | null {
  try {
    const parsed: unknown = JSON.parse(value)
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error(`${label} must be a JSON object.`)
    if (requireEntries && Object.keys(parsed).length === 0) throw new Error(`${label} must not be empty.`)
    return parsed as JsonDocument
  } catch (error) {
    throw error instanceof Error ? error : new Error(`${label} is not valid JSON.`)
  }
}

export function RegisterRoute() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const productsQuery = useProducts({ limit: 100 })
  const createRun = useCreateJob()
  const [sourceProductId, setSourceProductId] = useState(searchParams.get('source') ?? '')
  const [referenceProductId, setReferenceProductId] = useState('')
  const [parameterManifest, setParameterManifest] = useState('')
  const [parametersSha256, setParametersSha256] = useState('')
  const [algorithmVersions, setAlgorithmVersions] = useState('')
  const [modelVersions, setModelVersions] = useState('{}')
  const [codeRevision, setCodeRevision] = useState('')
  const [environmentFingerprint, setEnvironmentFingerprint] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const products = productsQuery.data?.pages.flatMap((page) => page.items) ?? []
  const canSubmit = Boolean(sourceProductId && referenceProductId && parameterManifest.trim() && parametersSha256.trim() && algorithmVersions.trim() && codeRevision.trim() && environmentFingerprint.trim())
  const selectedSource = useMemo(() => products.find((product) => product.id === sourceProductId), [products, sourceProductId])

  function submit() {
    try {
      setFormError(null)
      if (sourceProductId === referenceProductId) throw new Error('Source and reference must be two distinct persisted products.')
      if (!/^[0-9a-f]{64}$/i.test(parametersSha256.trim())) throw new Error('Parameter SHA-256 must be exactly 64 hexadecimal characters.')
      createRun.mutate({
        input: {
          sourceProductId,
          referenceProductId,
          parameterManifest: parseDocument(parameterManifest, 'Parameter manifest', true) as JsonDocument,
          parametersSha256: parametersSha256.trim().toLowerCase(),
          algorithmVersions: parseDocument(algorithmVersions, 'Algorithm versions', true) as JsonDocument,
          modelVersions: parseDocument(modelVersions, 'Model versions') as JsonDocument,
          codeRevision: codeRevision.trim(),
          environmentFingerprint: environmentFingerprint.trim(),
        },
        idempotencyKey: createIdempotencyKey(),
      }, { onSuccess: (run) => navigate(`/jobs/${run.id}`) })
    } catch (error) {
      setFormError(error instanceof Error ? error.message : 'The run definition is invalid.')
    }
  }

  return <div className="mx-auto max-w-4xl p-6">
    <PageHeader eyebrow="Registration" title="New persisted run" description="Choose two persisted products and submit an explicit immutable run definition. This interface does not calculate preflight estimates." />
    {productsQuery.isLoading && <LoadingState label="Loading persisted products" />}
    {productsQuery.error && <ErrorState code={isSeleneApiError(productsQuery.error) ? productsQuery.error.code : 'REQUEST_FAILED'} message={isSeleneApiError(productsQuery.error) ? productsQuery.error.message : 'Persisted products could not be loaded.'} />}
    {!productsQuery.isLoading && !productsQuery.error && products.length === 0 && <EmptyState title="NO PERSISTED PRODUCTS" description="A run cannot be created until both source and reference products have been persisted." />}
      {products.length > 0 && <div className="mt-6 space-y-6 border border-hairline p-5">
      <section><h2 className="text-section-title">01 · Persisted products</h2><p className="mt-1 text-caption text-mute">No reference candidates or overlap values are manufactured here.</p><div className="mt-4 grid gap-4 sm:grid-cols-2"><ProductSelect label="Source product" value={sourceProductId} products={products} onChange={setSourceProductId} /><ProductSelect label="Reference product" value={referenceProductId} products={products} onChange={setReferenceProductId} excludeId={sourceProductId} /></div>{selectedSource && <p className="mt-2 text-micro text-mute">Source payload type: {selectedSource.payloadType}; only stored product metadata is used.</p>}</section>
      <section className="border-t border-hairline pt-5"><h2 className="text-section-title">02 · Explicit execution definition</h2><p className="mt-1 text-caption text-mute">The service stores this definition but does not run a synthetic scientific pipeline. All values below must come from the actual operator/toolchain.</p><div className="mt-4 grid gap-4"><JsonField label="Parameter manifest *" value={parameterManifest} onChange={setParameterManifest} placeholder={'{"operator_defined_parameter": "value"}'} /><label className="text-caption"><span className="text-mute">Parameter manifest SHA-256 *</span><input value={parametersSha256} onChange={(event) => setParametersSha256(event.target.value)} className="mt-1 w-full border border-hairline bg-canvas px-3 py-2 font-mono text-caption focus:outline-none" /></label><JsonField label="Algorithm versions *" value={algorithmVersions} onChange={setAlgorithmVersions} placeholder={'{"registration_engine": "actual-version"}'} /><JsonField label="Model versions (may be empty)" value={modelVersions} onChange={setModelVersions} placeholder="{}" /><div className="grid gap-4 sm:grid-cols-2"><label className="text-caption"><span className="text-mute">Code revision *</span><input value={codeRevision} onChange={(event) => setCodeRevision(event.target.value)} className="mt-1 w-full border border-hairline bg-canvas px-3 py-2 text-caption focus:outline-none" /></label><label className="text-caption"><span className="text-mute">Environment fingerprint *</span><input value={environmentFingerprint} onChange={(event) => setEnvironmentFingerprint(event.target.value)} className="mt-1 w-full border border-hairline bg-canvas px-3 py-2 text-caption focus:outline-none" /></label></div></div></section>
      <section className="border-t border-hairline pt-5"><h2 className="text-section-title">03 · Persisted preflight</h2><p className="mt-1 text-caption text-mute">No persisted preflight record is exposed by the current API. No overlap, illumination, GSD, or candidate score is estimated in the client.</p></section>
      {formError && <ErrorState code="INVALID_RUN_DEFINITION" message={formError} />}
      {createRun.error && <ErrorState code={isSeleneApiError(createRun.error) ? createRun.error.code : 'REQUEST_FAILED'} message={isSeleneApiError(createRun.error) ? createRun.error.message : 'The run could not be persisted.'} />}
      <div className="flex justify-between border-t border-hairline pt-5">{productsQuery.hasNextPage ? <Button variant="secondary" onClick={() => productsQuery.fetchNextPage()} disabled={productsQuery.isFetchingNextPage}>{productsQuery.isFetchingNextPage ? 'Loading products…' : 'Load more products'}</Button> : <span />}<Button variant="primary" disabled={!canSubmit || createRun.isPending} onClick={submit}>{createRun.isPending ? 'Persisting…' : '[+] Create persisted run'}</Button></div>
    </div>}
  </div>
}

function ProductSelect({ label, value, products, onChange, excludeId }: { label: string; value: string; products: { id: string; productIdentity: string; payloadType: string }[]; onChange: (value: string) => void; excludeId?: string }) {
  return <label className="text-caption"><span className="text-mute">{label} *</span><select value={value} onChange={(event) => onChange(event.target.value)} className="mt-1 w-full border border-hairline bg-canvas px-3 py-2 text-caption focus:outline-none"><option value="">Select a persisted product…</option>{products.filter((product) => product.id !== excludeId).map((product) => <option key={product.id} value={product.id}>{product.productIdentity} · {product.payloadType} · {product.id}</option>)}</select></label>
}

function JsonField({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder: string }) {
  return <label className="text-caption"><span className="text-mute">{label}</span><textarea value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} rows={4} className="mt-1 w-full border border-hairline bg-canvas px-3 py-2 font-mono text-caption focus:outline-none" /></label>
}
