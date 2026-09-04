import { seleneApi, type ApiRequestOptions } from '@/services/api/client'
import type { ApiKnowledgeEdge, ApiKnowledgeEntity, ApiSemanticGraph, CursorPage } from '@/services/api/contracts'
import type { KnowledgeEdge, KnowledgeGraphData, KnowledgeNode, KnowledgeQueryRequest } from '@/types/knowledge'

export function knowledgeNodeFromApi(entity: ApiKnowledgeEntity): KnowledgeNode {
  return {
    id: entity.id,
    type: entity.entity_type,
    label: entity.label,
    externalId: entity.external_id,
    properties: entity.properties,
    locationGeojson: entity.location_geojson,
    locationCrs: entity.location_crs,
    locationSrid: entity.location_srid,
    createdAt: entity.created_at,
  }
}

export function knowledgeEdgeFromApi(edge: ApiKnowledgeEdge): KnowledgeEdge {
  return {
    id: edge.id,
    source: edge.source_entity_id,
    target: edge.target_entity_id,
    relation: edge.relation_type,
    properties: edge.properties,
    weight: edge.weight,
    createdAt: edge.created_at,
  }
}

export function graphFromApi(graph: ApiSemanticGraph): KnowledgeGraphData {
  return {
    nodes: graph.nodes.map(knowledgeNodeFromApi),
    edges: graph.edges.map(knowledgeEdgeFromApi),
    nextCursor: graph.next_cursor,
    edgesTruncated: graph.edges_truncated ?? false,
    relationshipExpansions: (graph.relationship_expansions ?? []).map((expansion) => ({
      entityId: expansion.entity_id,
      neighborsPath: expansion.neighbors_path,
    })),
  }
}

export const knowledgeRepository = {
  async query(request: KnowledgeQueryRequest, options?: ApiRequestOptions): Promise<KnowledgeGraphData> {
    const graph = await seleneApi.get<ApiSemanticGraph>('knowledge/query', {
      ...options,
      query: { query: request.query, entity_type: request.entityType, relation_type: request.relationType, cursor: request.cursor, limit: request.limit ?? 50 },
    })
    return graphFromApi(graph)
  },

  async getEntity(id: string, options?: ApiRequestOptions): Promise<KnowledgeNode> {
    return knowledgeNodeFromApi(await seleneApi.get<ApiKnowledgeEntity>(`knowledge/entities/${encodeURIComponent(id)}`, options))
  },

  async listEntities(filters: { entityType?: string; cursor?: string; limit?: number } = {}, options?: ApiRequestOptions) {
    const page = await seleneApi.get<CursorPage<ApiKnowledgeEntity>>('knowledge/entities', {
      ...options,
      query: { entity_type: filters.entityType, cursor: filters.cursor, limit: filters.limit ?? 50 },
    })
    return { items: page.items.map(knowledgeNodeFromApi), nextCursor: page.next_cursor }
  },

  async getNeighbours(entityId: string, filters: { cursor?: string | null; limit?: number } = {}, options?: ApiRequestOptions): Promise<KnowledgeGraphData> {
    return graphFromApi(await seleneApi.get<ApiSemanticGraph>(`knowledge/entities/${encodeURIComponent(entityId)}/neighbors`, { ...options, query: { cursor: filters.cursor, limit: filters.limit ?? 50 } }))
  },
}
