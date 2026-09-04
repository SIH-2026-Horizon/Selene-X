import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TopBar } from './TopBar'
import type { SessionUser } from '@/repositories/authRepository'
import { authRepository } from '@/repositories/authRepository'

function renderTopBar(sessionUser: SessionUser | undefined, authenticationConfigured = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<TopBar sessionUser={sessionUser} authenticationConfigured={authenticationConfigured} />} />
          <Route path="/login" element={<div>login screen</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('TopBar role badge', () => {
  it('shows the role and initials once a session resolves', () => {
    renderTopBar({ username: 'dijo.benelen', displayName: 'Dijo Benelen', role: 'reviewer' })

    expect(screen.getByText('REVIEWER')).toBeInTheDocument()
    expect(screen.getByText('DB')).toBeInTheDocument()
  })

  it('shows an explicit sign-in state when there is no session', () => {
    renderTopBar(undefined)

    expect(screen.getByText('NOT SIGNED IN')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /sign in/i })).toHaveAttribute('href', '/login')
  })

  it('omits authentication controls when authentication is not configured', () => {
    renderTopBar(undefined, false)

    expect(screen.queryByText('ROLE')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /sign in/i })).not.toBeInTheDocument()
  })
})

describe('TopBar logout control', () => {
  it('does not render a logout control when there is no session', () => {
    renderTopBar(undefined)

    expect(screen.queryByRole('button', { name: /log out/i })).not.toBeInTheDocument()
  })

  it('calls the logout mutation and navigates to /login on success', async () => {
    const logoutSpy = vi.spyOn(authRepository, 'logout').mockResolvedValue(undefined)
    renderTopBar({ username: 'dijo.benelen', displayName: 'Dijo Benelen', role: 'reviewer' })

    fireEvent.click(screen.getByRole('button', { name: /log out/i }))

    await waitFor(() => expect(logoutSpy).toHaveBeenCalled())
    await waitFor(() => expect(screen.getByText('login screen')).toBeInTheDocument())
  })

  it('offers profile access and only exposes user administration to admins', () => {
    renderTopBar({ username: 'dijo.benelen', displayName: 'Dijo Benelen', role: 'reviewer' })

    expect(screen.getByRole('link', { name: /profile & security/i })).toHaveAttribute('href', '/profile')
    expect(screen.queryByRole('link', { name: /operator accounts/i })).not.toBeInTheDocument()
  })

  it('exposes operator administration from an admin account menu', () => {
    renderTopBar({ username: 'admin', displayName: 'System Admin', role: 'admin' })

    expect(screen.getByRole('link', { name: /operator accounts/i })).toHaveAttribute('href', '/admin/users')
  })
})
