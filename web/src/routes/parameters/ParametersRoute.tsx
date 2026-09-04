import { Link } from 'react-router-dom'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { LoadingState } from '@/components/ui/LoadingState'
import { PageHeader } from '@/components/ui/PageHeader'
import { usePersistedRunSummary } from '@/features/jobs/usePersistedRunSummary'
import { isSeleneApiError } from '@/services/api/client'

export function ParametersRoute() {
  const jobsQuery = usePersistedRunSummary()
  const jobs = [...(jobsQuery.data?.items ?? [])].sort((left, right) => right.updatedAt.localeCompare(left.updatedAt))

  return <div className="flex flex-col gap-5 p-6">
    <PageHeader
      eyebrow="Research / Configuration"
      title="Persisted parameters"
      description="Parameter manifests and hashes are recorded with each persisted registration run. This view does not infer a separate parameter-set record."
    />
    {jobsQuery.isLoading && <LoadingState label="Loading persisted run parameter definitions" />}
    {jobsQuery.error && <ErrorState code={isSeleneApiError(jobsQuery.error) ? jobsQuery.error.code : 'REQUEST_FAILED'} message={isSeleneApiError(jobsQuery.error) ? jobsQuery.error.message : 'Persisted run parameter definitions could not be loaded.'} />}
    {!jobsQuery.isLoading && !jobsQuery.error && jobs.length === 0 && <EmptyState title="NO PERSISTED PARAMETER DEFINITIONS" description="No stored runs are available. Parameter definitions appear here only after a run is persisted." />}
    {!jobsQuery.isLoading && !jobsQuery.error && jobs.length > 0 && <><div className="overflow-x-auto border border-hairline scrollbar-hairline"><table className="w-full min-w-[840px] border-collapse text-caption"><thead className="bg-surface-soft"><tr>{['RUN UUID', 'PARAMETER MANIFEST', 'SHA-256', 'CODE REVISION', 'UPDATED'].map((heading) => <th key={heading} className="border-b border-hairline px-3 py-2 text-left text-micro font-medium uppercase tracking-wide text-mute">{heading}</th>)}</tr></thead><tbody>{jobs.map((job) => <tr key={job.id} className="border-b border-hairline last:border-b-0 hover:bg-surface-soft"><td className="px-3 py-2 font-medium"><Link to={`/jobs/${job.id}`} className="text-accent hover:underline">{job.id}</Link></td><td className="px-3 py-2">{job.parameterManifestAvailable && job.parameterManifest ? <details><summary className="cursor-pointer text-accent">View persisted manifest</summary><pre className="mt-2 max-w-md whitespace-pre-wrap break-words border border-hairline p-2 text-micro text-mute">{JSON.stringify(job.parameterManifest, null, 2)}</pre></details> : 'Unavailable in persisted storage'}</td><td className="px-3 py-2 font-mono text-micro">{job.parametersSha256}</td><td className="px-3 py-2">{job.codeRevision}</td><td className="px-3 py-2 tabular-nums text-mute">{new Date(job.updatedAt).toISOString()}</td></tr>)}</tbody></table></div>{jobsQuery.data?.nextCursor && <p className="text-caption text-mute">Showing the latest loaded persisted run page. Open Jobs to load additional records.</p>}</>}
  </div>
}
