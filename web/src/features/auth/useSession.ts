import { useQuery } from '@tanstack/react-query'
import { useOutletContext } from 'react-router-dom'
import { authRepository, type SessionUser } from '@/repositories/authRepository'
import { isSeleneApiError } from '@/services/api/client'

export function useSession() {
  return useQuery({
    queryKey: ['session'],
    queryFn: ({ signal }) => authRepository.getSession({ signal }),
    retry: false,
    staleTime: 60_000,
    // Both AppShell and TopBar independently subscribe to this query. React
    // Query's default refetchOnMount ignores staleTime for an *errored*
    // query, so TopBar mounting while the session is in an error state would
    // otherwise trigger a refetch, flipping isLoading back to true and
    // unmounting TopBar again — an infinite mount/refetch loop. Session
    // freshness is instead driven explicitly by useLogin/useLogout, which
    // already update this query's cache directly.
    refetchOnMount: false,
  })
}

/**
 * The session, as read by a routed page rendered inside AppShell's <Outlet>.
 *
 * Do NOT call useSession() a second time from a routed page. AppShell
 * already owns the one active session-query observer and gates rendering
 * on it (redirecting to /login, or waiting, before any route renders at
 * all) — every routed page reaches this point only once that's settled.
 * A second independent useSession() observer mounting while the cached
 * query is in an *error* state (e.g. a 404 "auth not configured" response)
 * causes a mount/unmount refetch loop between AppShell and the observer
 * that never settles. AppShell instead passes its already-resolved session
 * down via <Outlet context={...}>; this hook reads that context.
 */
export function useRouteSession(): SessionUser | undefined {
  return useOutletContext<SessionUser | undefined>()
}

/**
 * A 404 means this deployment never mounted the auth routes at all (it is
 * running in UNAUTHENTICATED or EXTERNAL mode) — there is nothing to gate.
 * A 401 means auth *is* configured and this caller simply isn't logged in.
 * Anything else is not yet known (still loading, or an unrelated failure).
 */
export function authConfigurationState(error: unknown): 'not-configured' | 'unauthenticated' | 'unknown' {
  if (isSeleneApiError(error)) {
    if (error.status === 404) return 'not-configured'
    if (error.status === 401) return 'unauthenticated'
  }
  return 'unknown'
}
