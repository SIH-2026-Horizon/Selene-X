import { Link, useParams } from 'react-router-dom'
import { EmptyState } from '@/components/ui/EmptyState'
import { PageHeader } from '@/components/ui/PageHeader'

export function CampaignDetailRoute() {
  const { id } = useParams()
  return <div className="flex flex-col gap-6 p-6">
    <PageHeader eyebrow="Operations" title={`Campaign ${id ?? ''}`} description="No persisted campaign resource is defined by the current service." />
    <EmptyState title="NO PERSISTED CAMPAIGN" description="This identifier cannot be resolved because campaigns are not part of the service's persisted data model." actions={<Link to="/jobs" className="text-caption text-accent hover:underline">View persisted runs →</Link>} />
  </div>
}
