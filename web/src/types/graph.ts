import type { JsonDocument } from '@/services/api/contracts'

export interface RegistrationGraphNode {
  id: string
  type: string
  label: string
  attributes: JsonDocument
}

export interface RegistrationGraphEdge {
  id: string
  source: string
  target: string
  relation: string
  weight: number | null
}

export interface RegistrationGraph {
  nodes: RegistrationGraphNode[]
  edges: RegistrationGraphEdge[]
  nextCursor: string | null
  childCollectionsTruncated: Array<{
    collection: 'stages' | 'artifacts' | 'metrics' | 'reviews'
    limit: number
  }>
}
