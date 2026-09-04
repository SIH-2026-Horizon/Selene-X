import { describe, expect, it, vi, afterEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { SeleneApiError } from '@/services/api/client'
import { authRepository } from '@/repositories/authRepository'
import { authConfigurationState, useSession } from './useSession'

afterEach(() => vi.restoreAllMocks())

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('useSession', () => {
  it('resolves the session user on success', async () => {
    vi.spyOn(authRepository, 'getSession').mockResolvedValue({ username: 'a', displayName: 'A', role: 'admin' })

    const { result } = renderHook(() => useSession(), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual({ username: 'a', displayName: 'A', role: 'admin' })
  })

  it('classifies errors by status code', () => {
    const notConfigured = new SeleneApiError({ code: 'HTTP_404', message: 'not found', status: 404 })
    const unauthenticated = new SeleneApiError({ code: 'HTTP_401', message: 'unauthorized', status: 401 })

    expect(authConfigurationState(notConfigured)).toBe('not-configured')
    expect(authConfigurationState(unauthenticated)).toBe('unauthenticated')
    expect(authConfigurationState(undefined)).toBe('unknown')
  })
})
