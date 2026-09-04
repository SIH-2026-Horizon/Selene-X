import { Link } from 'react-router-dom'
import { EmptyState } from '@/components/ui/EmptyState'
import { PageHeader } from '@/components/ui/PageHeader'

export function CampaignsRoute() {
  return <div className="flex flex-col gap-6 p-6">
    <PageHeader eyebrow="Operations" title="Campaigns" description="Campaigns are not records in the current SELENE persisted data model." />
    <EmptyState title="CAMPAIGN RECORDS UNAVAILABLE" description="The service does not synthesize campaign records from products or runs. Use persisted runs and registration graphs for the available operational provenance views." actions={<><Link to="/jobs" className="text-caption text-accent hover:underline">View persisted runs →</Link><Link to="/graphs" className="text-caption text-accent hover:underline">View registration graphs →</Link></>} />
  </div>
}
