import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { authRepository } from '@/repositories/authRepository'
import { LoginRoute } from './LoginRoute'

function renderLoginRoute() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/login']}>
        <LoginRoute />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('LoginRoute', () => {
  it('submits the entered username and password', async () => {
    const loginSpy = vi.spyOn(authRepository, 'login').mockResolvedValue({ username: 'a', displayName: 'A', role: 'admin' })
    renderLoginRoute()

    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'operator' } })
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'a-password' } })
    fireEvent.click(screen.getByRole('button', { name: /log in/i }))

    await waitFor(() => expect(loginSpy).toHaveBeenCalledWith('operator', 'a-password'))
  })

  it('shows the server error message on failed login', async () => {
    const { SeleneApiError } = await import('@/services/api/client')
    vi.spyOn(authRepository, 'login').mockRejectedValue(
      new SeleneApiError({ code: 'unauthorized', message: 'The username or password is incorrect.', status: 401 }),
    )
    renderLoginRoute()

    fireEvent.change(screen.getByLabelText(/username/i), { target: { value: 'operator' } })
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'wrong' } })
    fireEvent.click(screen.getByRole('button', { name: /log in/i }))

    await waitFor(() => expect(screen.getByText(/username or password is incorrect/i)).toBeInTheDocument())
  })
})
