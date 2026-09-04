import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import type { KnowledgeGraphData } from '@/types/knowledge'

const hooks = vi.hoisted(() => ({ useKnowledgeQuery: vi.fn(), useKnowledgeNeighbours: vi.fn() }))

vi.mock('@/features/knowledge/useKnowledgeQuery', () => ({
  useKnowledgeQuery: hooks.useKnowledgeQuery,
  useKnowledgeNeighbours: hooks.useKnowledgeNeighbours,
}))
vi.mock('@/components/graph/KnowledgeGraph', () => ({ KnowledgeGraph: () => <div data-testid="knowledge-graph" /> }))

import { KnowledgeRoute } from './KnowledgeRoute'

const rootId = '00000000-0000-4000-8000-000000000001'
const graphPage: KnowledgeGraphData = {
  nodes: [{ id: rootId, type: 'CRATER', label: 'Persisted root', externalId: null, properties: {}, locationGeojson: null, locationCrs: null, locationSrid: null, createdAt: '2026-08-30T00:00:00Z' }],
  edges: [],
  nextCursor: null,
  edgesTruncated: true,
  relationshipExpansions: [{ entityId: rootId, neighborsPath: `/api/v1/knowledge/entities/${rootId}/neighbors` }],
}

describe('KnowledgeRoute bounded relationship expansion', () => {
  it('warns about omitted relationships and exposes the entity neighbour cursor path', async () => {
    hooks.useKnowledgeQuery.mockReturnValue({ data: { pages: [graphPage] }, isLoading: false, error: null, hasNextPage: false })
    hooks.useKnowledgeNeighbours.mockReturnValue({ data: undefined, isLoading: false, error: null, hasNextPage: false })

    render(<MemoryRouter initialEntries={['/knowledge?q=Persisted']}><KnowledgeRoute /></MemoryRouter>)

    expect(await screen.findByRole('alert')).toHaveTextContent('RELATIONSHIP EXPANSION PARTIAL')
    fireEvent.click(screen.getByRole('button', { name: 'Inspect Persisted root relationships →' }))
    expect(hooks.useKnowledgeNeighbours).toHaveBeenLastCalledWith(rootId)
    expect(screen.getByText(`PERSISTED RELATIONSHIP PAGES / Persisted root`)).toBeInTheDocument()
  })
})
