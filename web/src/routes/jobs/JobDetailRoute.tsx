import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useJobDetail } from '@/features/jobs/useJobs'
import { useJobLiveUpdates } from '@/features/jobs/useJobLiveUpdates'
import { jobsRepository } from '@/repositories/jobsRepository'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { LoadingState } from '@/components/ui/LoadingState'
import { MetadataGrid } from '@/components/ui/MetadataGrid'
import { PageHeader } from '@/components/ui/PageHeader'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { createIdempotencyKey, isSeleneApiError } from '@/services/api/client'
import { safeArtifactUrl } from '@/services/api/artifactUrl'
import { canCancelJob, isJobStateActive, type RunDetailCollection, type RunDetailCursors } from '@/types/job'

function documentText(value: unknown) { return JSON.stringify(value, null, 2) }

const EMPTY_DETAIL_CURSORS: RunDetailCursors = {
  stages: null,
  artifacts: null,
  metrics: null,
  events: null,
  reviews: null,
}

export function JobDetailRoute() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const detailQuery = useJobDetail(id)
  const job = detailQuery.data
  const [detailCursors, setDetailCursors] = useState<RunDetailCursors>(EMPTY_DETAIL_CURSORS)
  const [extraRecords, setExtraRecords] = useState<Record<RunDetailCollection, unknown[]>>({
    stages: [], artifacts: [], metrics: [], events: [], reviews: [],
  })
  const [loadingCollection, setLoadingCollection] = useState<RunDetailCollection | null>(null)
  const [collectionError, setCollectionError] = useState<unknown>(null)
  useJobLiveUpdates(id, job?.state)
  useEffect(() => {
    if (!job) return
    setDetailCursors(job.collectionCursors ?? EMPTY_DETAIL_CURSORS)
    setExtraRecords({ stages: [], artifacts: [], metrics: [], events: [], reviews: [] })
    setCollectionError(null)
  }, [job?.id])
  const cancelRun = useMutation({
    mutationFn: (idempotencyKey: string) => jobsRepository.cancelJob(id, idempotencyKey),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ['job', id] }); void queryClient.invalidateQueries({ queryKey: ['job', id, 'detail'] }); void queryClient.invalidateQueries({ queryKey: ['jobs'] }) },
  })

  if (detailQuery.isLoading) return <LoadingState label="Loading persisted run detail" />
  if (detailQuery.error) return <div className="p-6"><ErrorState code={isSeleneApiError(detailQuery.error) ? detailQuery.error.code : 'REQUEST_FAILED'} message={isSeleneApiError(detailQuery.error) ? detailQuery.error.message : 'The persisted run could not be loaded.'} /></div>
  if (!job) return <div className="p-6"><EmptyState title="RUN NOT FOUND" description={`No persisted run with UUID ${id}.`} /></div>

  const stages = [...job.stages, ...extraRecords.stages] as typeof job.stages
  const artifacts = [...job.artifacts, ...extraRecords.artifacts] as typeof job.artifacts
  const metrics = [...job.metrics, ...extraRecords.metrics] as typeof job.metrics
  const events = [...job.events, ...extraRecords.events] as typeof job.events
  const reviews = [...job.reviews, ...extraRecords.reviews] as typeof job.reviews
  const loadMore = async (resource: RunDetailCollection) => {
    const cursor = detailCursors[resource]
    if (!cursor) return
    setLoadingCollection(resource)
    setCollectionError(null)
    try {
      const page = await jobsRepository.getJobDetailCollection(id, resource, cursor)
      setExtraRecords((current) => ({ ...current, [resource]: [...current[resource], ...page.items] }))
      setDetailCursors((current) => ({ ...current, [resource]: page.nextCursor }))
    } catch (error) {
      setCollectionError(error)
    } finally {
      setLoadingCollection(null)
    }
  }

  return <div className="flex flex-col gap-6 p-6">
    <PageHeader eyebrow={`RUN ${job.id}`} title={<span>{job.sourceProductId} <span className="text-mute">→</span> {job.referenceProductId}</span>} description={<StatusBadge status={job.state} />} actions={<>{canCancelJob(job.state) && <Button variant="danger" onClick={() => cancelRun.mutate(createIdempotencyKey())} disabled={cancelRun.isPending}>Cancel persisted run</Button>}<Button variant="primary" onClick={() => navigate(`/jobs/${job.id}/review`)}>Review persisted records</Button></>} />
    {cancelRun.error && <ErrorState code={isSeleneApiError(cancelRun.error) ? cancelRun.error.code : 'REQUEST_FAILED'} message={isSeleneApiError(cancelRun.error) ? cancelRun.error.message : 'Cancellation could not be requested.'} />}
    <div className="grid gap-5 lg:grid-cols-2"><section className="border border-hairline p-4"><h2 className="text-section-title">Run definition</h2><div className="mt-3"><MetadataGrid columns={1} entries={[
      { label: 'Source product UUID', value: job.sourceProductId }, { label: 'Reference product UUID', value: job.referenceProductId }, { label: 'Execution state', value: job.state }, { label: 'Computed verdict', value: job.computedVerdict ?? 'N/A' }, { label: 'Effective disposition', value: job.effectiveDisposition }, { label: 'Code revision', value: job.codeRevision }, { label: 'Environment fingerprint', value: job.environmentFingerprint }, { label: 'Parameters SHA-256', value: job.parametersSha256 }, { label: 'Created', value: new Date(job.createdAt).toISOString() }, { label: 'Updated', value: new Date(job.updatedAt).toISOString() },
    ]} /></div><details className="mt-4"><summary className="cursor-pointer text-caption text-accent">Parameter manifest</summary><pre className="mt-2 whitespace-pre-wrap break-words border border-hairline p-2 text-micro text-mute">{job.parameterManifestAvailable && job.parameterManifest ? documentText(job.parameterManifest) : 'N/A / parameter manifest unavailable in storage'}</pre></details><details className="mt-3"><summary className="cursor-pointer text-caption text-accent">Algorithm versions</summary><pre className="mt-2 whitespace-pre-wrap break-words border border-hairline p-2 text-micro text-mute">{documentText(job.algorithmVersions)}</pre></details></section>
      <section className="border border-hairline p-4"><h2 className="text-section-title">Persisted stages</h2>{stages.length === 0 ? <p className="mt-3 text-caption text-mute">No runner-persisted stage records.</p> : <ol className="mt-3 divide-y divide-hairline">{[...stages].sort((a, b) => a.stage_ordinal - b.stage_ordinal || a.attempt - b.attempt).map((stage) => <li key={stage.id} className="py-3"><div className="flex items-center justify-between gap-3"><span className="font-medium">{stage.stage_name}</span><span className="text-caption">{stage.execution_state}</span></div><p className="mt-1 text-micro text-mute">ordinal {stage.stage_ordinal} · attempt {stage.attempt} · completed {stage.completed_at ? new Date(stage.completed_at).toISOString() : 'N/A'}</p>{stage.failure_document && <pre className="mt-2 whitespace-pre-wrap break-words text-micro text-danger">{documentText(stage.failure_document)}</pre>}</li>)}</ol>}<CollectionLoadMore collection="stages" cursor={detailCursors?.stages ?? null} loading={loadingCollection} onLoad={loadMore} /></section></div>
    <section className="border border-hairline p-4"><h2 className="text-section-title">Persisted artifacts</h2>{artifacts.length === 0 ? <p className="mt-3 text-caption text-mute">No published artifact records.</p> : <div className="mt-3 overflow-auto"><table className="w-full min-w-[720px] text-caption"><thead className="text-micro uppercase text-mute"><tr><th className="text-left">Kind</th><th className="text-left">Publication</th><th className="text-left">Media type</th><th className="text-left">URI</th></tr></thead><tbody>{artifacts.map((artifact) => <tr key={artifact.id} className="border-t border-hairline"><td className="py-2">{artifact.kind}</td><td>{artifact.publication_state}</td><td>{artifact.media_type}</td><td className="max-w-sm break-all">{safeArtifactLink(artifact.storage_uri)}</td></tr>)}</tbody></table></div>}<CollectionLoadMore collection="artifacts" cursor={detailCursors?.artifacts ?? null} loading={loadingCollection} onLoad={loadMore} /></section>
    <div className="grid gap-5 lg:grid-cols-2"><PersistedDocuments title="Metric reports" empty="No persisted metric reports." documents={metrics.map((metric) => ({ id: metric.id, heading: `${metric.report_kind} / ${metric.report_version}`, body: metric.report_document, meta: metric.computed_verdict ?? 'N/A' }))} /><PersistedDocuments title="Review history" empty="No persisted review decisions." documents={reviews.map((review) => ({ id: review.id, heading: `${review.decision} / ${review.reason_code}`, body: { note: review.note, source_computed_verdict: review.source_computed_verdict }, meta: new Date(review.recorded_at).toISOString() }))} /></div>
    <div className="grid gap-3 sm:grid-cols-3"><CollectionLoadMore collection="metrics" cursor={detailCursors?.metrics ?? null} loading={loadingCollection} onLoad={loadMore} /><CollectionLoadMore collection="reviews" cursor={detailCursors?.reviews ?? null} loading={loadingCollection} onLoad={loadMore} /></div>
    <section><div className="mb-2 text-micro font-medium uppercase tracking-wide text-mute">Persisted event log {isJobStateActive(job.state) ? '(polling)' : ''}</div><div role="log" className="h-64 overflow-auto bg-surface-dark p-3 font-mono text-caption text-canvas scrollbar-hairline">{events.length === 0 ? <span className="text-ash">no persisted events</span> : [...events].sort((a, b) => a.sequence - b.sequence).map((event) => <div key={event.id} className="mb-1 whitespace-pre-wrap"><span className="text-ash">{new Date(event.recorded_at).toISOString()}</span> <span className="text-accent">[{event.sequence} {event.event_type}]</span> {documentText(event.event_document)}</div>)}</div><CollectionLoadMore collection="events" cursor={detailCursors?.events ?? null} loading={loadingCollection} onLoad={loadMore} /></section>
    {collectionError && <ErrorState code={isSeleneApiError(collectionError) ? collectionError.code : 'REQUEST_FAILED'} message={isSeleneApiError(collectionError) ? collectionError.message : 'The next persisted detail page could not be loaded.'} />}
    <p className="text-micro text-mute">Export and retry are unavailable because no API operation for them is persisted. <Link to={`/graphs/${job.id}?center_type=run`} className="text-accent hover:underline">Open registration provenance graph →</Link></p>
  </div>
}

function safeArtifactLink(uri: string) { const safeUrl = safeArtifactUrl(uri); return safeUrl ? <a className="text-accent hover:underline" href={safeUrl} target="_blank" rel="noreferrer">{safeUrl}</a> : <span>{uri} <span className="text-micro text-mute">(unavailable: not a configured HTTPS artifact host)</span></span> }
function PersistedDocuments({ title, empty, documents }: { title: string; empty: string; documents: { id: string; heading: string; body: unknown; meta: string }[] }) { return <section className="border border-hairline p-4"><h2 className="text-section-title">{title}</h2>{documents.length === 0 ? <p className="mt-3 text-caption text-mute">{empty}</p> : <div className="mt-3 space-y-3">{documents.map((document) => <details key={document.id} className="border-b border-hairline pb-3"><summary className="cursor-pointer text-caption"><span className="font-medium">{document.heading}</span> <span className="text-mute">{document.meta}</span></summary><pre className="mt-2 whitespace-pre-wrap break-words text-micro text-mute">{documentText(document.body)}</pre></details>)}</div>}</section> }
function CollectionLoadMore({ collection, cursor, loading, onLoad }: { collection: RunDetailCollection; cursor: string | null; loading: RunDetailCollection | null; onLoad: (collection: RunDetailCollection) => void }) {
  if (!cursor) return null
  return <div className="mt-3"><Button variant="secondary" onClick={() => onLoad(collection)} disabled={loading !== null}>{loading === collection ? `Loading more ${collection}…` : `Load more persisted ${collection}`}</Button></div>
}
