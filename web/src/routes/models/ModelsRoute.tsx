import { Link } from 'react-router-dom'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { LoadingState } from '@/components/ui/LoadingState'
import { PageHeader } from '@/components/ui/PageHeader'
import { usePersistedRunSummary } from '@/features/jobs/usePersistedRunSummary'
import { isSeleneApiError } from '@/services/api/client'

interface PersistedModelVersion {
  runId: string
  modelKey: string
  declaredVersion: unknown
  updatedAt: string
}

function modelVersionsFromRuns(runs: ReturnType<typeof usePersistedRunSummary>['data']): PersistedModelVersion[] {
  return (runs?.items ?? []).flatMap((run) => Object.entries(run.modelVersions).map(([modelKey, declaredVersion]) => ({
    runId: run.id,
    modelKey,
    declaredVersion,
    updatedAt: run.updatedAt,
  }))).sort((left, right) => right.updatedAt.localeCompare(left.updatedAt) || left.modelKey.localeCompare(right.modelKey))
}

export function ModelsRoute() {
  const jobsQuery = usePersistedRunSummary()
  const models = modelVersionsFromRuns(jobsQuery.data)

  return <div className="flex flex-col gap-5 p-6">
    <PageHeader
      eyebrow="Research / Configuration"
      title="Persisted model versions"
      description="Declared model versions are returned from persisted run definitions. This is a run provenance summary, not a model registry."
    />
    {jobsQuery.isLoading && <LoadingState label="Loading persisted model versions" />}
    {jobsQuery.error && <ErrorState code={isSeleneApiError(jobsQuery.error) ? jobsQuery.error.code : 'REQUEST_FAILED'} message={isSeleneApiError(jobsQuery.error) ? jobsQuery.error.message : 'Persisted model versions could not be loaded.'} />}
    {!jobsQuery.isLoading && !jobsQuery.error && jobsQuery.data?.items.length === 0 && <EmptyState title="NO PERSISTED RUN DEFINITIONS" description="No stored runs are available from which to read declared model versions." />}
    {!jobsQuery.isLoading && !jobsQuery.error && (jobsQuery.data?.items.length ?? 0) > 0 && models.length === 0 && <EmptyState title="NO PERSISTED MODEL VERSIONS" description="Stored runs exist, but none declare entries in their model_versions document." />}
    {!jobsQuery.isLoading && !jobsQuery.error && models.length > 0 && <><div className="overflow-x-auto border border-hairline scrollbar-hairline"><table className="w-full min-w-[760px] border-collapse text-caption"><thead className="bg-surface-soft"><tr>{['MODEL KEY', 'DECLARED VERSION', 'RUN UUID', 'UPDATED'].map((heading) => <th key={heading} className="border-b border-hairline px-3 py-2 text-left text-micro font-medium uppercase tracking-wide text-mute">{heading}</th>)}</tr></thead><tbody>{models.map((model) => <tr key={`${model.runId}:${model.modelKey}`} className="border-b border-hairline last:border-b-0 hover:bg-surface-soft"><td className="px-3 py-2 font-medium">{model.modelKey}</td><td className="px-3 py-2"><code className="whitespace-pre-wrap break-words text-micro">{JSON.stringify(model.declaredVersion)}</code></td><td className="px-3 py-2"><Link to={`/jobs/${model.runId}`} className="text-accent hover:underline">{model.runId}</Link></td><td className="px-3 py-2 tabular-nums text-mute">{new Date(model.updatedAt).toISOString()}</td></tr>)}</tbody></table></div>{jobsQuery.data?.nextCursor && <p className="text-caption text-mute">Showing model declarations from the latest loaded persisted run page. Open Jobs to load additional records.</p>}</>}
  </div>
}
