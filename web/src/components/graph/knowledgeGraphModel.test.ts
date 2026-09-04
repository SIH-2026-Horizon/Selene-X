import { MultiDirectedGraph } from 'graphology'
import { describe, expect, it } from 'vitest'
import { populateKnowledgeGraph } from './knowledgeGraphModel'

describe('populateKnowledgeGraph', () => {
  it('keeps parallel persisted relationships with distinct stable edge IDs', () => {
    const graph = new MultiDirectedGraph()
    populateKnowledgeGraph(graph, {
      nodes: [
        { id: 'entity-a', type: 'CRATER', label: 'A', externalId: null, properties: {}, locationGeojson: null, locationCrs: null, locationSrid: null, createdAt: '2026-08-30T00:00:00Z' },
        { id: 'entity-b', type: 'OBSERVATION', label: 'B', externalId: null, properties: {}, locationGeojson: null, locationCrs: null, locationSrid: null, createdAt: '2026-08-30T00:00:00Z' },
      ],
      edges: [
        { id: 'edge-observed', source: 'entity-a', target: 'entity-b', relation: 'OBSERVED_IN', properties: {}, weight: null, createdAt: '2026-08-30T00:00:00Z' },
        { id: 'edge-derived', source: 'entity-a', target: 'entity-b', relation: 'DERIVED_FROM', properties: {}, weight: null, createdAt: '2026-08-30T00:00:01Z' },
      ],
      nextCursor: null,
      edgesTruncated: false,
      relationshipExpansions: [],
    }, null)

    expect(graph.size).toBe(2)
    expect(graph.hasEdge('edge-observed')).toBe(true)
    expect(graph.hasEdge('edge-derived')).toBe(true)
  })
})
