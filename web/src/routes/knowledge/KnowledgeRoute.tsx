import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useKnowledgeNeighbours, useKnowledgeQuery } from '@/features/knowledge/useKnowledgeQuery'
import { KnowledgeGraph } from '@/components/graph/KnowledgeGraph'
import { KnowledgeInspector } from '@/components/graph/KnowledgeInspector'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { LoadingState } from '@/components/ui/LoadingState'
import { NlpQueryInput } from '@/components/ui/NlpQueryInput'
import { isSeleneApiError } from '@/services/api/client'
import type { KnowledgeQueryRequest } from '@/types/knowledge'

export function KnowledgeRoute() {
  const [searchParams] = useSearchParams()
  const [request, setRequest] = useState<KnowledgeQueryRequest | null>(null)
  const [entityType, setEntityType] = useState('')
  const [relationType, setRelationType] = useState('')
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [expandedEntityId, setExpandedEntityId] = useState<string | null>(null)
  const query = useKnowledgeQuery(request)
  const neighboursQuery = useKnowledgeNeighbours(expandedEntityId)
  const graph = useMemo(() => {
    const nodes = new Map<string, NonNullable<typeof query.data>['pages'][number]['nodes'][number]>()
    const edges = new Map<string, NonNullable<typeof query.data>['pages'][number]['edges'][number]>()
    const relationshipExpansions = new Map<string, NonNullable<typeof query.data>['pages'][number]['relationshipExpansions'][number]>()
    for (const page of query.data?.pages ?? []) {
      for (const node of page.nodes) nodes.set(node.id, node)
      for (const edge of page.edges) edges.set(edge.id, edge)
      for (const expansion of page.relationshipExpansions) relationshipExpansions.set(expansion.entityId, expansion)
    }
    return {
      nodes: [...nodes.values()],
      edges: [...edges.values()],
      nextCursor: query.data?.pages.at(-1)?.nextCursor ?? null,
      edgesTruncated: (query.data?.pages ?? []).some((page) => page.edgesTruncated),
      relationshipExpansions: [...relationshipExpansions.values()],
    }
  }, [query.data])
  const expandedRelationships = useMemo(() => {
    const edges = new Map<string, NonNullable<typeof neighboursQuery.data>['pages'][number]['edges'][number]>()
    for (const page of neighboursQuery.data?.pages ?? []) for (const edge of page.edges) edges.set(edge.id, edge)
    return [...edges.values()]
  }, [neighboursQuery.data])
  useEffect(() => { const value = searchParams.get('q'); if (value) setRequest({ query: value }) }, [searchParams])
  useEffect(() => { if (query.data && !graph.nodes.some((node) => node.id === selectedNodeId)) setSelectedNodeId(graph.nodes[0]?.id ?? null) }, [graph.nodes, query.data, selectedNodeId])
  const selectedNode = graph.nodes.find((node) => node.id === selectedNodeId) ?? null

  function submit(queryText: string) { setRequest({ query: queryText.trim() || undefined, entityType: entityType || undefined, relationType: relationType || undefined }) }

  return <div className="flex h-full flex-col"><div className="border-b border-hairline p-4"><NlpQueryInput onSubmit={submit} loading={query.isLoading} examples={[]} /><div className="mt-3 grid gap-3 sm:grid-cols-2"><label className="text-caption text-mute">Stored entity type filter<input value={entityType} onChange={(event) => setEntityType(event.target.value)} placeholder="CRATER" className="mt-1 block w-full border border-hairline bg-canvas px-2 py-1.5 text-caption text-ink focus:outline-none" /></label><label className="text-caption text-mute">Stored relation type filter<input value={relationType} onChange={(event) => setRelationType(event.target.value)} placeholder="OBSERVED_IN" className="mt-1 block w-full border border-hairline bg-canvas px-2 py-1.5 text-caption text-ink focus:outline-none" /></label></div><p className="mt-3 text-micro text-mute">This is transparent lexical and exact-filter retrieval over persisted semantic entities and relationships. It does not infer morphology or similarity.</p></div>
    {!request && <div className="p-6"><EmptyState title="NO QUERY YET" description="Search persisted semantic labels, identifiers, entity types, or relationship types." /></div>}
    {query.isLoading && <LoadingState label="Querying persisted semantic graph" />}
    {query.error && <div className="p-6"><ErrorState code={isSeleneApiError(query.error) ? query.error.code : 'REQUEST_FAILED'} message={isSeleneApiError(query.error) ? query.error.message : 'The semantic graph could not be queried.'} /></div>}
    {query.data && graph.nodes.length === 0 && !query.hasNextPage && <div className="p-6"><EmptyState title="NO GRAPH RESULTS" description="No persisted semantic entities or relationships match this retrieval request." /></div>}
    {query.data && graph.nodes.length > 0 && <><div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_340px] divide-x divide-hairline"><div className="min-h-0"><KnowledgeGraph data={graph} selectedNodeId={selectedNodeId} onSelectNode={setSelectedNodeId} onExpandNode={setExpandedEntityId} /></div><aside className="overflow-y-auto p-4 scrollbar-hairline"><KnowledgeInspector node={selectedNode} /><div className="mt-5 border-t border-hairline pt-4"><div className="text-micro uppercase text-mute">Query records</div><ul className="mt-2 space-y-2">{graph.nodes.map((node) => <li key={node.id}><button onClick={() => setSelectedNodeId(node.id)} className="w-full text-left text-caption hover:text-accent"><span className="font-medium">{node.label}</span><br /><span className="text-micro text-mute">{node.type}</span></button></li>)}</ul>{query.hasNextPage && <button onClick={() => query.fetchNextPage()} disabled={query.isFetchingNextPage} className="mt-4 border border-hairline px-3 py-1.5 text-caption hover:bg-surface-soft">{query.isFetchingNextPage ? 'Loading…' : 'Load more persisted graph records'}</button>}</div></aside></div>{graph.edgesTruncated && <section role="alert" className="border-t border-hairline bg-surface-soft p-4 text-caption"><p><strong>RELATIONSHIP EXPANSION PARTIAL.</strong> This bounded query omitted one or more persisted relationships. Inspect the named entity’s neighbour pages before treating its relationships as complete.</p><div className="mt-3 flex flex-wrap gap-2">{graph.relationshipExpansions.map((expansion) => { const entity = graph.nodes.find((node) => node.id === expansion.entityId); return <button key={expansion.entityId} onClick={() => setExpandedEntityId(expansion.entityId)} className="border border-hairline px-3 py-1.5 text-caption text-accent hover:bg-canvas">Inspect {entity?.label ?? expansion.entityId} relationships →</button> })}</div></section>}{expandedEntityId && <section className="border-t border-hairline p-4"><h2 className="text-section-title">PERSISTED RELATIONSHIP PAGES / {graph.nodes.find((node) => node.id === expandedEntityId)?.label ?? expandedEntityId}</h2><p className="mt-1 text-caption text-mute">This is the explicit cursor path for the selected entity’s relationships.</p>{neighboursQuery.isLoading && <LoadingState label="Loading persisted relationship page" />}{neighboursQuery.error && <ErrorState code={isSeleneApiError(neighboursQuery.error) ? neighboursQuery.error.code : 'REQUEST_FAILED'} message={isSeleneApiError(neighboursQuery.error) ? neighboursQuery.error.message : 'Persisted relationship pages could not be loaded.'} />}{!neighboursQuery.isLoading && !neighboursQuery.error && <><ul className="mt-3 divide-y divide-hairline">{expandedRelationships.map((edge) => <li key={edge.id} className="py-2 text-caption">{edge.source} <span className="text-mute">—[{edge.relation}]→</span> {edge.target}</li>)}</ul>{expandedRelationships.length === 0 && <p className="mt-3 text-caption text-mute">No persisted relationships were returned for this entity.</p>}{neighboursQuery.hasNextPage && <button onClick={() => neighboursQuery.fetchNextPage()} disabled={neighboursQuery.isFetchingNextPage} className="mt-3 border border-hairline px-3 py-1.5 text-caption hover:bg-surface-soft">{neighboursQuery.isFetchingNextPage ? 'Loading…' : 'Load more persisted relationships'}</button>}</>}</section>}</>}
    {query.data && graph.nodes.length === 0 && query.hasNextPage && <div className="p-6"><button onClick={() => query.fetchNextPage()} disabled={query.isFetchingNextPage} className="border border-hairline px-3 py-2 text-caption hover:bg-surface-soft">{query.isFetchingNextPage ? 'Loading…' : 'Load more persisted graph records'}</button></div>}
  </div>
}
