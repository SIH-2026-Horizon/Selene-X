import { useInfiniteQuery } from '@tanstack/react-query'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { registrationGraphRepository } from '@/repositories/registrationGraphRepository'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { LoadingState } from '@/components/ui/LoadingState'
import { PageHeader } from '@/components/ui/PageHeader'
import { isSeleneApiError } from '@/services/api/client'

export function GraphDetailRoute() {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const centerType = searchParams.get('center_type') === 'product' ? 'product' : searchParams.get('center_type') === 'run' ? 'run' : undefined
  const graphQuery = useInfiniteQuery({ queryKey: ['registration-provenance-graph', id, centerType], initialPageParam: null as string | null, queryFn: ({ signal, pageParam }) => registrationGraphRepository.getGraph(id, centerType, { cursor: pageParam }, { signal }), getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined })
  if (graphQuery.isLoading) return <LoadingState label="Loading registration provenance graph" />
  if (graphQuery.error) return <div className="p-6"><ErrorState code={isSeleneApiError(graphQuery.error) ? graphQuery.error.code : 'REQUEST_FAILED'} message={isSeleneApiError(graphQuery.error) ? graphQuery.error.message : 'The registration provenance graph could not be loaded.'} /></div>
  const nodes = new Map<string, NonNullable<typeof graphQuery.data>['pages'][number]['nodes'][number]>()
  const edges = new Map<string, NonNullable<typeof graphQuery.data>['pages'][number]['edges'][number]>()
  const truncations = new Map<string, NonNullable<typeof graphQuery.data>['pages'][number]['childCollectionsTruncated'][number]>()
  for (const page of graphQuery.data?.pages ?? []) {
    for (const node of page.nodes) nodes.set(node.id, node)
    for (const edge of page.edges) edges.set(edge.id, edge)
    for (const truncation of page.childCollectionsTruncated) truncations.set(truncation.collection, truncation)
  }
  const graph = { nodes: [...nodes.values()], edges: [...edges.values()], childCollectionsTruncated: [...truncations.values()] }
  if (graph.nodes.length === 0 && !graphQuery.hasNextPage) return <div className="p-6"><EmptyState title="NO PERSISTED PROVENANCE RECORDS" description="No registration provenance nodes or relationships are available for this center." /></div>
  const nodeLabels = new Map(graph.nodes.map((node) => [node.id, node.label]))
  const truncatedRunIds = graph.nodes.filter((node) => node.type === 'run' && node.id.startsWith('run:')).map((node) => node.id.slice('run:'.length))
  return <div className="flex flex-col gap-6 p-6"><PageHeader eyebrow="Operations" title="Registration provenance graph" description="DB-derived product, run, stage, artifact, metric, and review relationships. This is distinct from the semantic lunar knowledge graph." />{graph.childCollectionsTruncated.length > 0 && <section role="alert" className="border border-hairline bg-surface-soft p-4 text-caption"><p><strong>PROVENANCE CHILD RECORDS PARTIAL.</strong> The graph loaded a bounded slice of {graph.childCollectionsTruncated.map((truncation) => `${truncation.collection} (limit ${truncation.limit})`).join(', ')}. It is not a complete child-history view.</p><div className="mt-3 flex flex-wrap gap-3">{truncatedRunIds.map((runId) => <Link key={runId} to={`/jobs/${runId}`} className="text-accent hover:underline">Open run detail for cursor pages →</Link>)}</div></section>}<div className="grid gap-5 lg:grid-cols-2"><section className="border border-hairline p-4"><h2 className="text-section-title">Persisted nodes ({graph.nodes.length})</h2><ul className="mt-3 divide-y divide-hairline">{graph.nodes.map((node) => <li key={node.id} className="py-2 text-caption"><span className="font-medium">{node.label}</span><br /><span className="text-micro text-mute">{node.type} · {node.id}</span><pre className="mt-1 whitespace-pre-wrap break-words text-micro text-mute">{JSON.stringify(node.attributes, null, 2)}</pre></li>)}</ul></section><section className="border border-hairline p-4"><h2 className="text-section-title">Persisted relationships ({graph.edges.length})</h2>{graph.edges.length === 0 ? <p className="mt-3 text-caption text-mute">No persisted relationships in loaded graph pages.</p> : <ul className="mt-3 divide-y divide-hairline">{graph.edges.map((edge) => <li key={edge.id} className="py-2 text-caption"><span className="font-medium">{nodeLabels.get(edge.source) ?? edge.source}</span> <span className="text-mute">—[{edge.relation}]→</span> <span className="font-medium">{nodeLabels.get(edge.target) ?? edge.target}</span>{edge.weight !== null && <span className="ml-2 text-micro text-mute">weight {edge.weight}</span>}</li>)}</ul>}</section></div>{graphQuery.hasNextPage && <button onClick={() => graphQuery.fetchNextPage()} disabled={graphQuery.isFetchingNextPage} className="self-start border border-hairline px-3 py-1.5 text-caption hover:bg-surface-soft">{graphQuery.isFetchingNextPage ? 'Loading…' : 'Load more provenance records'}</button>}</div>
}
