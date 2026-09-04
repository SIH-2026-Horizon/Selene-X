import { useEffect } from 'react'
import { Navigate, Outlet } from 'react-router-dom'
import { TopBar } from './TopBar'
import { SideNavigation } from './SideNavigation'
import { CommandPalette } from './CommandPalette'
import { LoadingState } from '@/components/ui/LoadingState'
import { useCommandPaletteStore } from '@/stores/commandPaletteStore'
import { useApplyTheme } from '@/stores/themeStore'
import { authConfigurationState, useSession } from '@/features/auth/useSession'

export function AppShell() {
  const toggle = useCommandPaletteStore((s) => s.toggle)
  const sessionQuery = useSession()
  const authState = authConfigurationState(sessionQuery.error)
  useApplyTheme()

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        toggle()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [toggle])

  if (sessionQuery.isLoading) return <LoadingState label="Checking session" />
  if (authState === 'unauthenticated') {
    return <Navigate to="/login" replace />
  }

  return (
    <div className="motion-enter flex h-screen flex-col">
      <TopBar sessionUser={sessionQuery.data} authenticationConfigured={authState !== 'not-configured'} />
      <div className="flex min-h-0 flex-1">
        <SideNavigation sessionUser={sessionQuery.data} />
        <main className="min-w-0 flex-1 overflow-y-auto scrollbar-hairline">
          {/* Routed pages read the session via useRouteSession(), not a second
           * useSession() call — see that hook's docstring for why a second
           * query observer here causes a mount/refetch loop once this query
           * is in an error state (e.g. a 404 "auth not configured" response). */}
          <Outlet context={sessionQuery.data} />
        </main>
      </div>
      <CommandPalette />
    </div>
  )
}
