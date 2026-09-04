import { Link, useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { useJobs } from '@/features/jobs/useJobs'
import { buttonClassName } from '@/components/ui/buttonStyles'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { LoadingState } from '@/components/ui/LoadingState'
import { StatusBadge } from '@/components/ui/StatusBadge'
import { Button } from '@/components/ui/Button'
import { isSeleneApiError } from '@/services/api/client'
import { isJobStateActive } from '@/types/job'

export function OverviewRoute() {
  const jobsQuery = useJobs()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const jobs = jobsQuery.data?.pages.flatMap((page) => page.items) ?? []
  const activity = [
    { label: 'ACTIVE (LOADED)', value: jobs.filter((job) => isJobStateActive(job.state)).length },
    { label: 'SUCCEEDED (LOADED)', value: jobs.filter((job) => job.state === 'succeeded').length },
    { label: 'FAILED / CANCELLED', value: jobs.filter((job) => job.state === 'failed' || job.state === 'cancelled').length },
    { label: 'REJECTED DISPOSITIONS', value: jobs.filter((job) => job.effectiveDisposition === 'rejected').length },
  ]
  const recentJobs = [...jobs].sort((left, right) => right.updatedAt.localeCompare(left.updatedAt)).slice(0, 8)

  return <div className="flex flex-col gap-8 p-6">
    <div>
      <h1 className="text-display">SELENE-XR</h1>
      <p className="mt-1 max-w-2xl text-body">Persisted lunar registration provenance and semantic knowledge records.</p>
      <div className="mt-4 flex items-center gap-3">
        <Link to="/register" className={buttonClassName('primary')}>[+] New registration</Link>
        <Link to="/catalog" className={buttonClassName('secondary')}>Explore catalogue</Link>
        <Link to="/knowledge" className={buttonClassName('ghost')}>Semantic knowledge</Link>
      </div>
    </div>

    {jobsQuery.isLoading && <LoadingState label="Loading persisted runs" />}
    {jobsQuery.error && <ErrorState code={isSeleneApiError(jobsQuery.error) ? jobsQuery.error.code : 'REQUEST_FAILED'} message={isSeleneApiError(jobsQuery.error) ? jobsQuery.error.message : 'The run list could not be loaded.'} />}
    {!jobsQuery.isLoading && !jobsQuery.error && <>
      <section>
        <div className="mb-2 text-micro font-medium uppercase tracking-wide text-mute">Run activity (loaded persisted records)</div>
        <div className="grid grid-cols-2 gap-px border border-hairline bg-hairline sm:grid-cols-4">{activity.map((item) => <div key={item.label} className="bg-canvas p-4"><div className="text-2xl font-bold tabular-nums">{item.value}</div><div className="mt-1 text-micro text-mute">{item.label}</div></div>)}</div>
        {jobsQuery.hasNextPage && <p className="mt-2 text-micro text-mute">Counts cover loaded cursor pages. Additional persisted runs are available.</p>}
      </section>
      <section>
        <div className="mb-2 flex items-center justify-between"><div className="text-micro font-medium uppercase tracking-wide text-mute">Recent persisted runs</div><Link to="/jobs" className="text-caption text-accent hover:underline">View all →</Link></div>
        {recentJobs.length === 0 ? <EmptyState title="NO PERSISTED RUNS" description="Create a run only after selecting two persisted products and supplying an explicit execution definition." /> : <div className="overflow-x-auto border border-hairline scrollbar-hairline"><table className="w-full min-w-[860px] border-collapse text-caption"><thead className="bg-surface-soft"><tr>{['RUN UUID', 'SOURCE PRODUCT', 'REFERENCE PRODUCT', 'STATE', 'COMPUTED VERDICT', 'UPDATED'].map((heading) => <th key={heading} className="border-b border-hairline px-3 py-2 text-left text-micro font-medium uppercase tracking-wide text-mute">{heading}</th>)}</tr></thead><tbody>{recentJobs.map((job) => <tr key={job.id} className="border-b border-hairline last:border-b-0 hover:bg-surface-soft"><td className="px-3 py-2 font-medium"><Link to={`/jobs/${job.id}`} className="text-accent hover:underline">{job.id}</Link></td><td className="px-3 py-2">{job.sourceProductId}</td><td className="px-3 py-2">{job.referenceProductId}</td><td className="px-3 py-2"><StatusBadge status={job.state} /></td><td className="px-3 py-2">{job.computedVerdict ?? 'N/A'}</td><td className="px-3 py-2 tabular-nums text-mute">{new Date(job.updatedAt).toISOString()}</td></tr>)}</tbody></table></div>}
      </section>
    </>}
    {jobsQuery.hasNextPage && <Button variant="secondary" onClick={() => jobsQuery.fetchNextPage()} disabled={jobsQuery.isFetchingNextPage}>{jobsQuery.isFetchingNextPage ? 'Loading persisted runs…' : 'Load more persisted runs'}</Button>}
    <section className="border border-hairline p-4"><div className="text-micro font-medium uppercase tracking-wide text-mute">Query semantic knowledge records</div><form className="mt-2 flex items-center gap-3" onSubmit={(event) => { event.preventDefault(); navigate(`/knowledge?q=${encodeURIComponent(query)}`) }}><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search persisted semantic entity labels and identifiers" className="w-full bg-transparent text-body placeholder:text-ash focus:outline-none" /><Button variant="primary" type="submit">Search →</Button></form></section>
  </div>
}
