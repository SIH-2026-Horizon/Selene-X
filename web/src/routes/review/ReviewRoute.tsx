import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useJobDetail } from '@/features/jobs/useJobs'
import { useRouteSession } from '@/features/auth/useSession'
import { useSubmitReviewDecision } from '@/features/review/useSubmitReviewDecision'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { LoadingState } from '@/components/ui/LoadingState'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { createIdempotencyKey, isSeleneApiError } from '@/services/api/client'
import { safeArtifactUrl } from '@/services/api/artifactUrl'

function imageUrl(artifact: { storage_uri: string; media_type: string }) { return artifact.media_type.toLowerCase().startsWith('image/') ? safeArtifactUrl(artifact.storage_uri) : null }

export function ReviewRoute() {
  const { id = '' } = useParams()
  const detailQuery = useJobDetail(id)
  const submitReview = useSubmitReviewDecision(id)
  const sessionUser = useRouteSession()
  const roleForbidden = Boolean(sessionUser && sessionUser.role !== 'reviewer' && sessionUser.role !== 'admin')
  const [reasonCode, setReasonCode] = useState('')
  const [note, setNote] = useState('')
  if (detailQuery.isLoading) return <LoadingState label="Loading persisted review records" />
  if (detailQuery.error) return <div className="p-6"><ErrorState code={isSeleneApiError(detailQuery.error) ? detailQuery.error.code : 'REQUEST_FAILED'} message={isSeleneApiError(detailQuery.error) ? detailQuery.error.message : 'The persisted review records could not be loaded.'} /></div>
  const job = detailQuery.data
  if (!job) return <div className="p-6"><EmptyState title="RUN NOT FOUND" description={`No persisted run with UUID ${id}.`} /></div>
  const images = job.artifacts.flatMap((artifact) => { const url = imageUrl(artifact); return url ? [{ artifact, url }] : [] })
  const source = images.find(({ artifact }) => /source/i.test(artifact.kind))
  const reference = images.find(({ artifact }) => /reference/i.test(artifact.kind))
  const registered = images.find(({ artifact }) => /registered|output|warped/i.test(artifact.kind))
  const hasCorrespondence = job.artifacts.some((artifact) => /tie.?point|correspondence/i.test(artifact.kind))
  const reviewEligible = job.state === 'succeeded' && job.computedVerdict !== null
  const canSubmitReview = reviewEligible && !roleForbidden

  return <div className="flex flex-col gap-5 p-6">
    <div className="flex flex-wrap items-center gap-3 border-b border-hairline pb-4"><span className="text-section-title">REVIEW / {job.id}</span><StatusBadge status={job.state} /><span className="text-caption text-mute">Only persisted artifacts from configured HTTPS storage, metric reports, and immutable reviews are shown.</span></div>
    {!source || !reference || !registered || !hasCorrespondence ? <EmptyState title="MISSING_ARTIFACT" description="No persisted correspondence set and configured HTTPS source/reference/registered imagery combination is available for this run." /> : <section className="grid gap-px border border-hairline bg-hairline lg:grid-cols-3">{[source, reference, registered].map(({ artifact, url }) => <figure key={artifact.id} className="bg-canvas p-3"><figcaption className="mb-2 text-micro uppercase text-mute">{artifact.kind}</figcaption><img src={url} alt={`${artifact.kind} persisted artifact`} referrerPolicy="no-referrer" className="max-h-[54vh] w-full object-contain" /><p className="mt-2 break-all text-micro text-mute">{url}</p></figure>)}</section>}
    <section className="grid gap-5 lg:grid-cols-2"><div className="border border-hairline p-4"><h2 className="text-section-title">Persisted metric reports</h2>{job.metrics.length === 0 ? <p className="mt-3 text-caption text-mute">No persisted metric reports.</p> : <div className="mt-3 space-y-3">{job.metrics.map((metric) => <details key={metric.id} className="border-b border-hairline pb-3"><summary className="cursor-pointer text-caption">{metric.report_kind} / {metric.report_version} · {metric.computed_verdict ?? 'N/A'}</summary><pre className="mt-2 whitespace-pre-wrap break-words text-micro text-mute">{JSON.stringify(metric.report_document, null, 2)}</pre></details>)}</div>}</div><div className="border border-hairline p-4"><h2 className="text-section-title">Persisted reviews</h2>{job.reviews.length === 0 ? <p className="mt-3 text-caption text-mute">No persisted review decisions.</p> : <ul className="mt-3 divide-y divide-hairline">{job.reviews.map((review) => <li key={review.id} className="py-2 text-caption"><span className="font-medium">{review.decision}</span> · {review.reason_code}<br /><span className="text-mute">{review.note ?? 'N/A'} · {new Date(review.recorded_at).toISOString()}</span></li>)}</ul>}</div></section>
    {(job.collectionCursors?.metrics || job.collectionCursors?.reviews || job.collectionCursors?.artifacts) && <p className="text-caption text-mute">This review view shows initial persisted detail pages. Open the run detail to load additional artifacts, metric reports, or review history.</p>}
    <section className="border border-hairline p-4"><h2 className="text-section-title">Record review</h2><p className="mt-1 text-caption text-mute">The backend records immutable accepted or rejected decisions only after a run has succeeded with a persisted computed verdict.</p>{!reviewEligible && <p className="mt-2 text-caption text-warning">Review is unavailable until this run is <strong>succeeded</strong> and has a persisted computed verdict. Its current state is {job.state}; verdict: {job.computedVerdict ?? 'N/A'}.</p>}{roleForbidden && <p className="mt-2 text-caption text-warning">Reviewer or Admin role is required to record a review decision.</p>}<div className="mt-3 grid gap-3 sm:grid-cols-[1fr_2fr_auto_auto]"><input value={reasonCode} onChange={(event) => setReasonCode(event.target.value)} placeholder="Reason code" disabled={!reviewEligible} className="border border-hairline bg-canvas px-3 py-2 text-caption focus:outline-none disabled:text-ash" /><input value={note} onChange={(event) => setNote(event.target.value)} placeholder="Note (required for rejection)" disabled={!reviewEligible} className="border border-hairline bg-canvas px-3 py-2 text-caption focus:outline-none disabled:text-ash" /><Button variant="primary" disabled={!canSubmitReview || !reasonCode || submitReview.isPending} onClick={() => submitReview.mutate({ decision: 'accepted', reasonCode, note, idempotencyKey: createIdempotencyKey() })}>Accept</Button><Button variant="danger" disabled={!canSubmitReview || !reasonCode || !note.trim() || submitReview.isPending} onClick={() => submitReview.mutate({ decision: 'rejected', reasonCode, note, idempotencyKey: createIdempotencyKey() })}>Reject</Button></div>{submitReview.error && <div className="mt-3"><ErrorState code={isSeleneApiError(submitReview.error) ? submitReview.error.code : 'REQUEST_FAILED'} message={isSeleneApiError(submitReview.error) ? submitReview.error.message : 'The review could not be persisted.'} /></div>}</section>
  </div>
}
