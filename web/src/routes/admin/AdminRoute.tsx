import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { ErrorState } from '@/components/ui/ErrorState'
import { LoadingState } from '@/components/ui/LoadingState'
import { PageHeader } from '@/components/ui/PageHeader'
import { usePlatformStatus } from '@/features/platform/usePlatformStatus'

function ProbeRow({ label, endpoint, status, ok, message }: { label: string; endpoint: string; status: number | null; ok: boolean; message: string }) {
  return <tr className="border-b border-hairline last:border-b-0"><td className="px-3 py-2 font-medium">{label}</td><td className="px-3 py-2 font-mono text-micro">{endpoint}</td><td className="px-3 py-2"><span className={ok ? 'text-success' : 'text-danger'}>{ok ? 'AVAILABLE' : 'UNAVAILABLE'}</span></td><td className="px-3 py-2 tabular-nums">{status ?? 'NO RESPONSE'}</td><td className="px-3 py-2 text-mute">{message}</td></tr>
}

export function AdminRoute() {
  const statusQuery = usePlatformStatus()
  const status = statusQuery.data

  return <div className="flex flex-col gap-5 p-6">
    <PageHeader
      eyebrow="System"
      title="Platform status"
      description="Live same-origin liveness, readiness, and version responses from the running SELENE service."
      actions={<><Link to="/admin/users" className="text-caption text-accent hover:underline">Operator accounts →</Link><Button variant="secondary" onClick={() => statusQuery.refetch()} disabled={statusQuery.isFetching}>{statusQuery.isFetching ? 'Refreshing…' : 'Refresh status'}</Button></>}
    />
    {statusQuery.isLoading && <LoadingState label="Checking same-origin platform status" />}
    {statusQuery.error && <ErrorState code="STATUS_REQUEST_FAILED" message="The platform status request could not be completed." />}
    {status && <><div className="overflow-x-auto border border-hairline scrollbar-hairline"><table className="w-full min-w-[760px] border-collapse text-caption"><thead className="bg-surface-soft"><tr>{['CHECK', 'ENDPOINT', 'STATE', 'HTTP', 'RESULT'].map((heading) => <th key={heading} className="border-b border-hairline px-3 py-2 text-left text-micro font-medium uppercase tracking-wide text-mute">{heading}</th>)}</tr></thead><tbody><ProbeRow label="Process liveness" {...status.liveness} /><ProbeRow label="Database readiness" {...status.readiness} /><ProbeRow label="Service version" {...status.version} /></tbody></table></div><section className="border border-hairline p-4"><h2 className="text-section-title">Service metadata</h2>{status.serviceVersion ? <dl className="mt-3 grid gap-3 text-caption sm:grid-cols-3"><div><dt className="text-micro uppercase tracking-wide text-mute">Service</dt><dd className="mt-1">{status.serviceVersion.service}</dd></div><div><dt className="text-micro uppercase tracking-wide text-mute">Version</dt><dd className="mt-1 font-mono">{status.serviceVersion.version}</dd></div><div><dt className="text-micro uppercase tracking-wide text-mute">Environment</dt><dd className="mt-1">{status.serviceVersion.environment}</dd></div></dl> : <p className="mt-2 text-caption text-mute">Version metadata is unavailable because the version endpoint did not return a successful service response.</p>}</section></>}
    <section className="border border-hairline p-4"><h2 className="text-section-title">Platform constraints</h2><ul className="mt-3 list-disc space-y-2 pl-5 text-caption text-mute"><li>The packaged web interface reaches the service through the same-origin proxy; the browser does not hold the local service credential.</li><li>Process liveness and PostgreSQL readiness are separate checks. A live process can be unavailable for persisted data while readiness fails.</li><li>This service exposes persisted products, runs, provenance, and knowledge records. It does not expose tenant, account, campaign, or general-purpose administration records.</li></ul></section>
  </div>
}
