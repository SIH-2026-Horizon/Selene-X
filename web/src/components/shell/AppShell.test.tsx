import { describe, expect, it, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { authRepository } from '@/repositories/authRepository'
import { SeleneApiError } from '@/services/api/client'
import { AppShell } from './AppShell'

afterEach(() => vi.restoreAllMocks())

function renderShell() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createMemoryRouter(
    [
      { path: '/login', element: <div>LOGIN PAGE</div> },
      { path: '/', element: <AppShell />, children: [{ index: true, element: <div>HOME</div> }] },
    ],
    { initialEntries: ['/'] },
  )
  return render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('AppShell session gate', () => {
  it('redirects to /login on a 401 session response', async () => {
    vi.spyOn(authRepository, 'getSession').mockRejectedValue(
      new SeleneApiError({ code: 'unauthorized', message: 'x', status: 401 }),
    )
    renderShell()

    await waitFor(() => expect(screen.getByText('LOGIN PAGE')).toBeInTheDocument())
  })

  it('renders the shell normally on a 404 (auth not configured)', async () => {
    vi.spyOn(authRepository, 'getSession').mockRejectedValue(
      new SeleneApiError({ code: 'not_found', message: 'x', status: 404 }),
    )
    renderShell()

    await waitFor(() => expect(screen.getByText('HOME')).toBeInTheDocument())
    expect(screen.queryByText('NOT SIGNED IN')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /sign in/i })).not.toBeInTheDocument()
  })

  it('renders the shell normally once a session resolves', async () => {
    vi.spyOn(authRepository, 'getSession').mockResolvedValue({ username: 'a', displayName: 'A', role: 'admin' })
    renderShell()

    await waitFor(() => expect(screen.getByText('HOME')).toBeInTheDocument())
  })
})
