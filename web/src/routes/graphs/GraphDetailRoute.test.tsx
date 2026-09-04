import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

const repository = vi.hoisted(() => ({ getGraph: vi.fn() }))

vi.mock('@/repositories/registrationGraphRepository', () => ({ registrationGraphRepository: repository }))

import { GraphDetailRoute } from './GraphDetailRoute'

const runId = '00000000-0000-4000-8000-000000000001'

describe('GraphDetailRoute bounded provenance', () => {
  it('discloses bounded child history and links to the run cursor pages', async () => {
    repository.getGraph.mockResolvedValue({
      nodes: [{ id: `run:${runId}`, type: 'run', label: `Run ${runId}`, attributes: {} }],
      edges: [],
      nextCursor: null,
      childCollectionsTruncated: [{ collection: 'artifacts', limit: 50 }],
    })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(<QueryClientProvider client={queryClient}><MemoryRouter initialEntries={[`/graphs/${runId}?center_type=run`]}><Routes><Route path="/graphs/:id" element={<GraphDetailRoute />} /></Routes></MemoryRouter></QueryClientProvider>)

    expect(await screen.findByRole('alert')).toHaveTextContent('PROVENANCE CHILD RECORDS PARTIAL')
    expect(screen.getByRole('link', { name: 'Open run detail for cursor pages →' })).toHaveAttribute('href', `/jobs/${runId}`)
  })
})
