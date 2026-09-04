import { describe, expect, it, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { authRepository } from '@/repositories/authRepository'
import type { SessionUser } from '@/repositories/authRepository'
import { UsersRoute } from './UsersRoute'

afterEach(() => vi.restoreAllMocks())

/**
 * UsersRoute reads the session via useRouteSession() (React Router's Outlet
 * context), the same way AppShell provides it in the real app — not a second
 * useSession() query. Route through a parent <Outlet context={sessionUser}>
 * so the component under test sees the same context shape it does in
 * production, rather than mocking authRepository.getSession directly.
 */
function renderUsersRoute(sessionUser: SessionUser | undefined) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Routes>
          <Route element={<Outlet context={sessionUser} />}>
            <Route path="/" element={<UsersRoute />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('UsersRoute', () => {
  it('shows a forbidden message for a non-admin session', () => {
    renderUsersRoute({ username: 'a', displayName: 'A', role: 'reviewer' })

    expect(screen.getByText(/admin role is required/i)).toBeInTheDocument()
  })

  it('lists accounts and creates a new one for an admin session', async () => {
    vi.spyOn(authRepository, 'listUsers').mockResolvedValue([
      { id: 'admin-uuid', username: 'admin', displayName: 'Admin', role: 'admin', isActive: true },
    ])
    const createSpy = vi.spyOn(authRepository, 'createUser').mockResolvedValue({
      id: 'new-analyst-uuid', username: 'new.analyst', displayName: 'New Analyst', role: 'analyst', isActive: true,
    })
    renderUsersRoute({ username: 'admin', displayName: 'Admin', role: 'admin' })

    expect(await screen.findByText('admin')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(/^username$/i), { target: { value: 'new.analyst' } })
    fireEvent.change(screen.getByLabelText(/display name/i), { target: { value: 'New Analyst' } })
    fireEvent.change(screen.getByLabelText(/^password$/i), { target: { value: 'a-strong-password' } })
    fireEvent.click(screen.getByRole('button', { name: /create account/i }))

    await waitFor(() =>
      expect(createSpy).toHaveBeenCalledWith({
        username: 'new.analyst',
        password: 'a-strong-password',
        role: 'analyst',
        displayName: 'New Analyst',
      }),
    )
  })

  it('changes another account\'s role via its row control', async () => {
    vi.spyOn(authRepository, 'listUsers').mockResolvedValue([
      { id: 'admin-uuid', username: 'admin', displayName: 'Admin', role: 'admin', isActive: true },
      { id: 'analyst-uuid', username: 'b.analyst', displayName: 'B Analyst', role: 'analyst', isActive: true },
    ])
    const updateSpy = vi.spyOn(authRepository, 'updateUser').mockResolvedValue({
      id: 'analyst-uuid', username: 'b.analyst', displayName: 'B Analyst', role: 'reviewer', isActive: true,
    })
    renderUsersRoute({ username: 'admin', displayName: 'Admin', role: 'admin' })

    await screen.findByText('b.analyst')

    const analystRow = screen.getByText('b.analyst').closest('tr') as HTMLElement
    fireEvent.change(within(analystRow).getByLabelText('Role for b.analyst'), { target: { value: 'reviewer' } })
    fireEvent.click(within(analystRow).getByRole('button', { name: /^save$/i }))

    await waitFor(() =>
      expect(updateSpy).toHaveBeenCalledWith('analyst-uuid', { role: 'reviewer' }),
    )
  })

  it('toggles another account\'s active status via its row control', async () => {
    vi.spyOn(authRepository, 'listUsers').mockResolvedValue([
      { id: 'admin-uuid', username: 'admin', displayName: 'Admin', role: 'admin', isActive: true },
      { id: 'analyst-uuid', username: 'b.analyst', displayName: 'B Analyst', role: 'analyst', isActive: true },
    ])
    const updateSpy = vi.spyOn(authRepository, 'updateUser').mockResolvedValue({
      id: 'analyst-uuid', username: 'b.analyst', displayName: 'B Analyst', role: 'analyst', isActive: false,
    })
    renderUsersRoute({ username: 'admin', displayName: 'Admin', role: 'admin' })

    await screen.findByText('b.analyst')

    const analystRow = screen.getByText('b.analyst').closest('tr') as HTMLElement
    fireEvent.click(within(analystRow).getByRole('button', { name: /^deactivate$/i }))

    await waitFor(() =>
      expect(updateSpy).toHaveBeenCalledWith('analyst-uuid', { isActive: false }),
    )
  })

  it('disables the role and active-status controls for the signed-in admin\'s own row', async () => {
    vi.spyOn(authRepository, 'listUsers').mockResolvedValue([
      { id: 'admin-uuid', username: 'admin', displayName: 'Admin', role: 'admin', isActive: true },
      { id: 'analyst-uuid', username: 'b.analyst', displayName: 'B Analyst', role: 'analyst', isActive: true },
    ])
    renderUsersRoute({ username: 'admin', displayName: 'Admin', role: 'admin' })

    await screen.findByText('b.analyst')

    expect(screen.getByLabelText('Role for admin')).toBeDisabled()
    const adminRow = screen.getByLabelText('Role for admin').closest('tr') as HTMLElement
    for (const button of within(adminRow).getAllByRole('button')) {
      expect(button).toBeDisabled()
    }

    expect(screen.getByLabelText('Role for b.analyst')).not.toBeDisabled()
  })
})
