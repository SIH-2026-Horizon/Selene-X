import { useEffect, useRef } from 'react'
import { MultiDirectedGraph } from 'graphology'
import Sigma from 'sigma'
import forceAtlas2 from 'graphology-layout-forceatlas2'
import type { KnowledgeGraphData } from '@/types/knowledge'
import { useResolvedTheme } from '@/stores/themeStore'
import { populateKnowledgeGraph } from './knowledgeGraphModel'

interface KnowledgeGraphProps {
  data: KnowledgeGraphData
  selectedNodeId: string | null
  onSelectNode: (id: string) => void
  onExpandNode?: (id: string) => void
}

const PALETTE = {
  light: { label: '#201d1d', node: '#f1eeee', edge: 'rgba(32,29,29,0.3)' },
  dark: { label: '#f5f3f2', node: '#3a3636', edge: 'rgba(255,255,255,0.25)' },
} as const

export function KnowledgeGraph({ data, selectedNodeId, onSelectNode, onExpandNode }: KnowledgeGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const sigmaRef = useRef<Sigma | null>(null)
  const graphRef = useRef<MultiDirectedGraph | null>(null)
  const selectedRef = useRef<string | null>(selectedNodeId)
  const theme = useResolvedTheme()
  const themeRef = useRef(theme)

  useEffect(() => {
    if (!containerRef.current) return
    const graph = new MultiDirectedGraph()
    graphRef.current = graph

    // Node/edge fill color is resolved per-frame from themeRef/selectedRef rather than
    // stored as a graph attribute, so a theme or selection change is just a refresh —
    // no need to rewrite every node's stored color.
    const sigma = new Sigma(graph, containerRef.current, {
      // A parent that just became visible (e.g. a freshly-selected tab) can commit
      // before the browser finishes laying it out, momentarily reporting zero height.
      allowInvalidContainer: true,
      renderLabels: true,
      labelFont: "'JetBrains Mono', monospace",
      labelSize: 12,
      labelColor: { color: PALETTE[themeRef.current].label },
      minCameraRatio: 0.08,
      maxCameraRatio: 12,
      nodeReducer: (node, nodeData) => ({
        ...nodeData,
        color: node === selectedRef.current ? '#007aff' : PALETTE[themeRef.current].node,
      }),
      edgeReducer: (_edge, edgeData) => ({
        ...edgeData,
        color: PALETTE[themeRef.current].edge,
      }),
    })
    sigmaRef.current = sigma

    sigma.on('clickNode', ({ node }) => onSelectNode(node))
    sigma.on('doubleClickNode', ({ node }) => onExpandNode?.(node))

    const resizeObserver = new ResizeObserver(() => sigma.resize())
    resizeObserver.observe(containerRef.current)

    return () => {
      resizeObserver.disconnect()
      sigma.kill()
      sigmaRef.current = null
      graphRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    selectedRef.current = selectedNodeId
    sigmaRef.current?.refresh()
  }, [selectedNodeId])

  useEffect(() => {
    themeRef.current = theme
    sigmaRef.current?.setSetting('labelColor', { color: PALETTE[theme].label })
    sigmaRef.current?.refresh()
  }, [theme])

  useEffect(() => {
    const graph = graphRef.current
    const sigma = sigmaRef.current
    if (!graph || !sigma) return

    graph.clear()
    populateKnowledgeGraph(graph, data, selectedNodeId)

    if (graph.order > 0) {
      forceAtlas2.assign(graph, { iterations: 120, settings: { gravity: 1, scalingRatio: 12 } })
    }
    sigma.refresh()
  }, [data, selectedNodeId])

  return (
    <div className="relative h-full w-full bg-canvas">
      <div ref={containerRef} className="h-full w-full" aria-hidden="true" />
      <p className="sr-only">
        Knowledge graph with {data.nodes.length} entities and {data.edges.length} relationships. Use the results
        table for a text-based view of the same data.
      </p>
    </div>
  )
}
