import { Link } from 'react-router-dom'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { LoadingState } from '@/components/ui/LoadingState'
import { PageHeader } from '@/components/ui/PageHeader'
import { usePersistedAuditActivity } from '@/features/audit/usePersistedAuditActivity'
import { isSeleneApiError } from '@/services/api/client'

function activityDetails(activity: ReturnType<typeof usePersistedAuditActivity>['data'][number]) {
  if (activity.kind === 'event') {
    return <><span>{activity.event.event_type}{activity.event.execution_state ? ` · ${activity.event.execution_state}` : ''}</span><details className="mt-1"><summary className="cursor-pointer text-accent">Event document</summary><pre className="mt-2 max-w-md whitespace-pre-wrap break-words border border-hairline p-2 text-micro text-mute">{JSON.stringify(activity.event.event_document, null, 2)}</pre></details></>
  }
  return <><span>{activity.review.decision} · {activity.review.reason_code}</span><div className="mt-1 text-micro text-mute">{activity.review.note ?? 'No persisted note.'}{activity.review.source_computed_verdict ? ` · source verdict: ${activity.review.source_computed_verdict}` : ''}</div></>
}

export function AuditRoute() {
  const activityQuery = usePersistedAuditActivity()
  const activity = activityQuery.data ?? []

  return <div className="flex flex-col gap-5 p-6">
    <PageHeader
      eyebrow="System"
      title="Persisted run activity"
      description="Append-only run events and immutable review decisions returned for persisted runs. This is activity visibility, not a complete platform-wide audit log."
    />
    {activityQuery.isLoading && <LoadingState label="Loading persisted run events and reviews" />}
    {activityQuery.error && <ErrorState code={isSeleneApiError(activityQuery.error) ? activityQuery.error.code : 'REQUEST_FAILED'} message={isSeleneApiError(activityQuery.error) ? activityQuery.error.message : 'Persisted run activity could not be loaded.'} />}
    {!activityQuery.isLoading && !activityQuery.error && !activityQuery.hasRuns && <EmptyState title="NO PERSISTED RUN ACTIVITY" description="No persisted runs are available. Events and reviews appear only for stored runs." />}
    {!activityQuery.isLoading && !activityQuery.error && activityQuery.hasRuns && activity.length === 0 && <EmptyState title="NO PERSISTED EVENTS OR REVIEWS" description="Stored runs are available, but their event and review API records are empty." />}
    {!activityQuery.isLoading && !activityQuery.error && activity.length > 0 && <div className="overflow-x-auto border border-hairline scrollbar-hairline"><table className="w-full min-w-[920px] border-collapse text-caption"><thead className="bg-surface-soft"><tr>{['RECORDED', 'KIND', 'RUN UUID', 'ACTOR SUBJECT UUID', 'PERSISTED DETAIL'].map((heading) => <th key={heading} className="border-b border-hairline px-3 py-2 text-left text-micro font-medium uppercase tracking-wide text-mute">{heading}</th>)}</tr></thead><tbody>{activity.map((item) => <tr key={`${item.kind}:${item.id}`} className="border-b border-hairline last:border-b-0 align-top hover:bg-surface-soft"><td className="px-3 py-2 tabular-nums text-mute">{new Date(item.recordedAt).toISOString()}</td><td className="px-3 py-2 uppercase">{item.kind}</td><td className="px-3 py-2"><Link to={`/jobs/${item.runId}`} className="text-accent hover:underline">{item.runId}</Link></td><td className="px-3 py-2 font-mono text-micro">{item.actorSubjectId ?? 'N/A'}</td><td className="px-3 py-2">{activityDetails(item)}</td></tr>)}</tbody></table></div>}
    {!activityQuery.isLoading && !activityQuery.error && activityQuery.hasRuns && <p className="text-caption text-mute">Showing initial event and review pages for the latest {activityQuery.loadedRunCount} loaded runs. Open an individual run to load additional records.{activityQuery.hasMore ? ' Additional persisted activity is available.' : ''}</p>}
  </div>
}
