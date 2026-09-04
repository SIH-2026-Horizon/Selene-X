import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ProfileRoute } from './ProfileRoute'
import { authRepository, type SessionUser } from '@/repositories/authRepository'

function renderProfile(sessionUser: SessionUser) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Routes>
          <Route element={<Outlet context={sessionUser} />}>
            <Route path="/" element={<ProfileRoute />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('ProfileRoute', () => {
  it('persists a display name and password update through the profile API', async () => {
    const updateProfile = vi.spyOn(authRepository, 'updateProfile').mockResolvedValue({ username: 'operator', displayName: 'Updated Operator', role: 'reviewer' })
    renderProfile({ username: 'operator', displayName: 'Operator', role: 'reviewer' })

    fireEvent.change(screen.getByLabelText(/display name/i), { target: { value: 'Updated Operator' } })
    fireEvent.change(screen.getByLabelText(/current password/i), { target: { value: 'old-password' } })
    fireEvent.change(screen.getByLabelText(/^new password$/i), { target: { value: 'new-password' } })
    fireEvent.click(screen.getByRole('button', { name: /save profile/i }))

    await waitFor(() => expect(updateProfile).toHaveBeenCalledWith({ displayName: 'Updated Operator', currentPassword: 'old-password', newPassword: 'new-password' }))
  })

  it('renders the server-assigned role as read-only information', () => {
    renderProfile({ username: 'operator', displayName: 'Operator', role: 'reviewer' })

    expect(screen.getByText('REVIEWER')).toBeInTheDocument()
    expect(screen.queryByLabelText(/^role$/i)).not.toBeInTheDocument()
  })
})
