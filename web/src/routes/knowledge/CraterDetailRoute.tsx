import { useParams } from 'react-router-dom'
import { useCrater, useCraterNeighbours, useCraterObservations } from '@/features/knowledge/useCraterQueries'
import { KnowledgeGraph } from '@/components/graph/KnowledgeGraph'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { LoadingState } from '@/components/ui/LoadingState'
import { MetadataGrid } from '@/components/ui/MetadataGrid'
import { PageHeader } from '@/components/ui/PageHeader'
import { isSeleneApiError } from '@/services/api/client'
import type { KnowledgeGraphData } from '@/types/knowledge'

function mergeGraphPages(pages: KnowledgeGraphData[] | undefined): KnowledgeGraphData {
  const nodes = new Map<string, KnowledgeGraphData['nodes'][number]>()
  const edges = new Map<string, KnowledgeGraphData['edges'][number]>()
  const relationshipExpansions = new Map<string, KnowledgeGraphData['relationshipExpansions'][number]>()
  for (const page of pages ?? []) {
    for (const node of page.nodes) nodes.set(node.id, node)
    for (const edge of page.edges) edges.set(edge.id, edge)
    for (const expansion of page.relationshipExpansions) relationshipExpansions.set(expansion.entityId, expansion)
  }
  return {
    nodes: [...nodes.values()],
    edges: [...edges.values()],
    nextCursor: pages?.at(-1)?.nextCursor ?? null,
    edgesTruncated: (pages ?? []).some((page) => page.edgesTruncated),
    relationshipExpansions: [...relationshipExpansions.values()],
  }
}

export function CraterDetailRoute() {
  const { id = '' } = useParams()
  const craterQuery = useCrater(id)
  const observationsQuery = useCraterObservations(id)
  const neighboursQuery = useCraterNeighbours(id)
  if (craterQuery.isLoading) return <LoadingState label="Loading persisted crater entity" />
  if (craterQuery.error) return <div className="p-6"><ErrorState code={isSeleneApiError(craterQuery.error) ? craterQuery.error.code : 'REQUEST_FAILED'} message={isSeleneApiError(craterQuery.error) ? craterQuery.error.message : 'The crater entity could not be loaded.'} /></div>
  const crater = craterQuery.data
  if (!crater) return <div className="p-6"><EmptyState title="CRATER NOT FOUND" description={`No persisted CRATER entity with UUID ${id}.`} /></div>
  const observations = mergeGraphPages(observationsQuery.data?.pages)
  const neighbours = mergeGraphPages(neighboursQuery.data?.pages)
  return <div className="flex flex-col gap-6 p-6"><PageHeader eyebrow="Semantic knowledge" title={`CRATER / ${crater.label}`} description="Generic persisted CRATER entity; properties and observations are shown exactly as stored." /><div className="grid gap-5 lg:grid-cols-2"><section className="border border-hairline p-4"><MetadataGrid columns={1} entries={[{ label: 'UUID', value: crater.id }, { label: 'External ID', value: crater.externalId ?? 'N/A' }, { label: 'Location CRS', value: crater.locationCrs ?? 'N/A / no persisted location' }, { label: 'Created', value: new Date(crater.createdAt).toISOString() }]} /><details className="mt-4"><summary className="cursor-pointer text-caption text-accent">Persisted crater properties</summary><pre className="mt-2 whitespace-pre-wrap break-words border border-hairline p-2 text-micro text-mute">{JSON.stringify(crater.properties, null, 2)}</pre></details></section><section className="border border-hairline p-4"><h2 className="text-section-title">Persisted observations</h2>{observationsQuery.isLoading ? <LoadingState label="Loading observation edges" /> : observationsQuery.error ? <ErrorState code={isSeleneApiError(observationsQuery.error) ? observationsQuery.error.code : 'REQUEST_FAILED'} message={isSeleneApiError(observationsQuery.error) ? observationsQuery.error.message : 'Observation edges could not be loaded.'} /> : observations.nodes.length === 0 && !observationsQuery.hasNextPage ? <p className="mt-3 text-caption text-mute">No persisted observation nodes or observation edges.</p> : <><ul className="mt-3 divide-y divide-hairline">{observations.nodes.filter((node) => node.id !== crater.id).map((node) => <li key={node.id} className="py-2 text-caption"><span className="font-medium">{node.label}</span><br /><span className="text-micro text-mute">{node.type} · {node.id}</span></li>)}</ul>{observationsQuery.hasNextPage && <button onClick={() => observationsQuery.fetchNextPage()} disabled={observationsQuery.isFetchingNextPage} className="mt-3 border border-hairline px-3 py-1.5 text-caption hover:bg-surface-soft">{observationsQuery.isFetchingNextPage ? 'Loading…' : 'Load more observations'}</button>}</>}</section></div><section className="min-h-[360px] border border-hairline"><div className="border-b border-hairline p-3 text-micro uppercase text-mute">Persisted generic relationships</div>{neighboursQuery.isLoading ? <LoadingState label="Loading semantic neighbors" /> : neighboursQuery.error ? <div className="p-4"><ErrorState code={isSeleneApiError(neighboursQuery.error) ? neighboursQuery.error.code : 'REQUEST_FAILED'} message={isSeleneApiError(neighboursQuery.error) ? neighboursQuery.error.message : 'Semantic neighbors could not be loaded.'} /></div> : neighbours.nodes.length === 0 && !neighboursQuery.hasNextPage ? <div className="p-4"><EmptyState title="NO PERSISTED RELATIONSHIPS" description="This CRATER entity has no stored semantic neighbor records." /></div> : <><KnowledgeGraph data={neighbours} selectedNodeId={crater.id} onSelectNode={() => undefined} />{neighboursQuery.hasNextPage && <div className="border-t border-hairline p-3"><button onClick={() => neighboursQuery.fetchNextPage()} disabled={neighboursQuery.isFetchingNextPage} className="border border-hairline px-3 py-1.5 text-caption hover:bg-surface-soft">{neighboursQuery.isFetchingNextPage ? 'Loading…' : 'Load more relationships'}</button></div>}</>}</section></div>
}
