import type { JsonDocument } from '@/services/api/contracts'

export type KnowledgeEntityType = string
export type KnowledgeRelationType = string

export const KNOWLEDGE_ENTITY_MARKER: Record<string, string> = {
  CRATER: '[C]',
  OBSERVATION: '[O]',
  PAYLOAD: '[P]',
  REFERENCE_PRODUCT: '[R]',
  TERRAIN: '[T]',
  MORPHOLOGY_FEATURE: '[F]',
  REGISTRATION_JOB: '[J]',
  DATA_PRODUCT: '[D]',
}

export interface KnowledgeNode {
  id: string
  type: KnowledgeEntityType
  label: string
  externalId: string | null
  properties: JsonDocument
  locationGeojson: JsonDocument | null
  locationCrs: string | null
  locationSrid: number | null
  createdAt: string
}

export interface KnowledgeEdge {
  id: string
  source: string
  target: string
  relation: KnowledgeRelationType
  properties: JsonDocument
  weight: number | null
  createdAt: string
}

export interface KnowledgeGraphData {
  nodes: KnowledgeNode[]
  edges: KnowledgeEdge[]
  nextCursor: string | null
  edgesTruncated: boolean
  relationshipExpansions: Array<{
    entityId: string
    neighborsPath: string
  }>
}

export interface KnowledgeQueryRequest {
  query?: string
  entityType?: string
  relationType?: string
  cursor?: string
  limit?: number
}
