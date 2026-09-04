import { MultiDirectedGraph } from 'graphology'
import type { KnowledgeGraphData } from '@/types/knowledge'
import { KNOWLEDGE_ENTITY_MARKER } from '@/types/knowledge'

/** Write every persisted relationship by its stable record ID, including parallels. */
export function populateKnowledgeGraph(
  graph: MultiDirectedGraph,
  data: KnowledgeGraphData,
  selectedNodeId: string | null,
) {
  for (const node of data.nodes) {
    graph.addNode(node.id, {
      label: `${KNOWLEDGE_ENTITY_MARKER[node.type] ?? '[?]'} ${node.label}`,
      size: node.id === selectedNodeId ? 11 : 7,
      x: Math.random(),
      y: Math.random(),
    })
  }
  for (const edge of data.edges) {
    if (graph.hasNode(edge.source) && graph.hasNode(edge.target) && !graph.hasEdge(edge.id)) {
      graph.addDirectedEdgeWithKey(edge.id, edge.source, edge.target, {
        label: edge.relation,
        size: 1,
      })
    }
  }
}
