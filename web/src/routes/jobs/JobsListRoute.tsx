import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useJobs } from '@/features/jobs/useJobs'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { LoadingState } from '@/components/ui/LoadingState'
import { PageHeader } from '@/components/ui/PageHeader'
import { SearchInput } from '@/components/ui/SearchInput'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { isSeleneApiError } from '@/services/api/client'
import { parseJobStateFilter, RUN_STATE_FILTERS } from '@/types/job'

export function JobsListRoute() {
  const jobsQuery = useJobs()
  const [searchParams, setSearchParams] = useSearchParams()
  const [query, setQuery] = useState('')
  const stateFilter = parseJobStateFilter(searchParams.get('state'))
  const loadedJobs = useMemo(() => jobsQuery.data?.pages.flatMap((page) => page.items) ?? [], [jobsQuery.data])
  const filtered = useMemo(() => loadedJobs.filter((job) => (stateFilter === 'all' || job.state === stateFilter) && (!query || `${job.id} ${job.sourceProductId} ${job.referenceProductId}`.toLowerCase().includes(query.toLowerCase()))), [loadedJobs, query, stateFilter])

  return <div className="flex flex-col gap-4 p-6">
    <PageHeader eyebrow="Registration" title="Persisted runs" description="States and dispositions below are returned by the persisted API." />
    <div className="flex flex-wrap items-center gap-3"><SearchInput placeholder="Search persisted run or product UUID…" value={query} onChange={(event) => setQuery(event.target.value)} /><div className="flex flex-wrap gap-1">{RUN_STATE_FILTERS.map((filter) => <button key={filter.value} onClick={() => setSearchParams(filter.value === 'all' ? {} : { state: filter.value })} className={'rounded px-2.5 py-1 text-caption ' + (stateFilter === filter.value ? 'bg-ink text-canvas' : 'text-body hover:bg-surface-soft')}>{filter.label}</button>)}</div></div>
    {jobsQuery.isLoading && <LoadingState label="Loading persisted runs" />}
    {jobsQuery.error && <ErrorState code={isSeleneApiError(jobsQuery.error) ? jobsQuery.error.code : 'REQUEST_FAILED'} message={isSeleneApiError(jobsQuery.error) ? jobsQuery.error.message : 'Persisted runs could not be loaded.'} />}
    {!jobsQuery.isLoading && !jobsQuery.error && filtered.length === 0 && <EmptyState title="NO PERSISTED RUNS" description={jobsQuery.hasNextPage ? 'No loaded run page matches the current state or identifier filter. Load more records to continue searching.' : 'No stored runs match the current state or identifier filter.'} />}
    {filtered.length > 0 && <div className="overflow-x-auto border border-hairline scrollbar-hairline"><table className="w-full min-w-[900px] border-collapse text-caption"><thead className="bg-surface-soft"><tr>{['RUN UUID', 'SOURCE PRODUCT', 'REFERENCE PRODUCT', 'STATE', 'COMPUTED VERDICT', 'DISPOSITION', 'UPDATED'].map((heading) => <th key={heading} className="border-b border-hairline px-3 py-2 text-left text-micro font-medium uppercase tracking-wide text-mute">{heading}</th>)}</tr></thead><tbody>{filtered.map((job) => <tr key={job.id} className="border-b border-hairline last:border-b-0 hover:bg-surface-soft"><td className="px-3 py-2 font-medium"><Link to={`/jobs/${job.id}`} className="text-accent hover:underline">{job.id}</Link></td><td className="px-3 py-2">{job.sourceProductId}</td><td className="px-3 py-2">{job.referenceProductId}</td><td className="px-3 py-2"><StatusBadge status={job.state} /></td><td className="px-3 py-2">{job.computedVerdict ?? 'N/A'}</td><td className="px-3 py-2">{job.effectiveDisposition}</td><td className="px-3 py-2 tabular-nums text-mute">{new Date(job.updatedAt).toISOString()}</td></tr>)}</tbody></table></div>}
    {jobsQuery.hasNextPage && <div className="flex items-center gap-3"><p className="text-micro text-mute">Additional persisted run pages are available.</p><button onClick={() => jobsQuery.fetchNextPage()} disabled={jobsQuery.isFetchingNextPage} className="border border-hairline px-3 py-1.5 text-caption hover:bg-surface-soft disabled:text-ash">{jobsQuery.isFetchingNextPage ? 'Loading…' : 'Load more'}</button></div>}
  </div>
}
