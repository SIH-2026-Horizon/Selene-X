import { afterEach, describe, expect, it, vi } from 'vitest'
import { authRepository } from './authRepository'

afterEach(() => vi.unstubAllGlobals())

describe('authRepository', () => {
  it('posts credentials to login and returns the session user', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ username: 'operator', display_name: 'Operator', role: 'reviewer' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const user = await authRepository.login('operator', 'a-password')

    expect(user).toEqual({ username: 'operator', displayName: 'Operator', role: 'reviewer' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/api/v1/auth/login')
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ username: 'operator', password: 'a-password' })
  })

  it('treats a 404 session response as auth not being configured', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 404 })))

    await expect(authRepository.getSession()).rejects.toMatchObject({ status: 404 })
  })

  it('treats a 401 session response as not logged in', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: { code: 'unauthorized', message: 'Authentication is required.' } }), {
          status: 401,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )

    await expect(authRepository.getSession()).rejects.toMatchObject({ status: 401 })
  })

  it('lists users and maps the roster', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            items: [{ id: 'account-uuid', username: 'a', display_name: 'A', role: 'admin', is_active: true }],
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    )

    const page = await authRepository.listUsers()

    expect(page).toEqual([{ id: 'account-uuid', username: 'a', displayName: 'A', role: 'admin', isActive: true }])
  })

  it('patches a user and returns the updated account', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ id: 'some-id', username: 'some-username', display_name: 'User', role: 'reviewer', is_active: true }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    const user = await authRepository.updateUser('some-id', { role: 'reviewer' })

    expect(user).toEqual({ id: 'some-id', username: 'some-username', displayName: 'User', role: 'reviewer', isActive: true })
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/api/v1/auth/users/some-id')
    expect((init as RequestInit).method).toBe('PATCH')
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ role: 'reviewer' })
  })

  it('patches the signed-in profile and maps the refreshed session user', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ username: 'operator', display_name: 'Updated Operator', role: 'reviewer' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const user = await authRepository.updateProfile({ displayName: 'Updated Operator', currentPassword: 'old', newPassword: 'new-password' })

    expect(user).toEqual({ username: 'operator', displayName: 'Updated Operator', role: 'reviewer' })
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toContain('/api/v1/auth/profile')
    expect((init as RequestInit).method).toBe('PATCH')
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ display_name: 'Updated Operator', current_password: 'old', new_password: 'new-password' })
  })
})
