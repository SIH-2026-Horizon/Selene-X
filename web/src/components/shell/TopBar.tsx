import { Link, useNavigate } from 'react-router-dom'
import { useCommandPaletteStore } from '@/stores/commandPaletteStore'
import { AsciiStatus } from '@/components/ui/AsciiStatus'
import { Button } from '@/components/ui/Button'
import type { SessionUser } from '@/repositories/authRepository'
import { useLogout } from '@/features/auth/useLogout'
import { ThemeToggle } from './ThemeToggle'

function initialsFor(displayName: string): string {
  const parts = displayName.trim().split(/\s+/).filter(Boolean)
  const first = parts[0]?.[0] ?? ''
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? '') : ''
  return `${first}${last}`.toUpperCase()
}

interface TopBarProps {
  /**
   * Passed down from AppShell's own session query rather than fetched here.
   * A second `useSession()` observer mounting inside the already-rendered
   * shell while the cached session query is in an error state (e.g. a 404
   * "auth not configured" response) causes an AppShell/TopBar mount-unmount
   * oscillation that never settles — see the useSession() query below and
   * the finding recorded in this feature's implementation ledger. Keep
   * TopBar as a plain presentational consumer of this prop instead of an
   * independent query subscriber.
   */
  sessionUser: SessionUser | undefined
  /** False when the deployment has no session-auth routes at all. */
  authenticationConfigured?: boolean
}

export function TopBar({ sessionUser, authenticationConfigured = true }: TopBarProps) {
  const openPalette = useCommandPaletteStore((s) => s.open)
  const navigate = useNavigate()
  const logout = useLogout()

  function handleLogout() {
    // useLogout()'s onSuccess already clears the cached ['session'] query,
    // but AppShell does not automatically refetch after a mutation — so the
    // next render would otherwise keep showing the (now stale) authenticated
    // shell until something triggers a session re-check. Navigate to /login
    // explicitly, mirroring how LoginRoute navigates to '/' on a successful
    // login.
    logout.mutate(undefined, { onSuccess: () => navigate('/login', { replace: true }) })
  }

  return (
    <header className="flex h-14 shrink-0 items-center gap-4 border-b border-hairline bg-canvas px-4">
      <img src="/brand/selene-xr-wordmark.svg" alt="SELENE-XR" className="brand-mark h-7 w-auto shrink-0" />

      <div className="mx-auto w-full max-w-xl">
        <button
          onClick={openPalette}
          className="flex w-full items-center gap-2 rounded border border-hairline bg-surface-soft px-3 py-1.5 text-left text-caption text-mute hover:border-hairline-strong"
        >
          <span aria-hidden="true">[?]</span>
          <span className="flex-1">Search persisted products, runs, or semantic entities…</span>
          <kbd className="rounded border border-hairline-strong px-1.5 py-0.5 text-micro">⌘K</kbd>
        </button>
      </div>

      <div className="flex items-center gap-4 whitespace-nowrap">
        <span className="flex items-center gap-1.5 text-caption">
          <AsciiStatus marker="dot" tone="muted" />
          <span className="text-mute">API STATUS NOT VERIFIED</span>
        </span>

        {sessionUser && (
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1.5 rounded border border-hairline px-2 py-1 text-micro">
              <span className="text-mute">ROLE</span>
              <span className="font-semibold">{sessionUser.role.toUpperCase()}</span>
            </span>
            <details className="relative">
              <summary
                aria-label="Open account menu"
                title={sessionUser.displayName}
                className="flex h-7 w-7 cursor-pointer list-none items-center justify-center rounded-full border border-hairline text-micro font-semibold marker:hidden focus:outline-none"
              >
                {initialsFor(sessionUser.displayName)}
              </summary>
              <div className="absolute right-0 z-20 mt-2 w-60 border border-hairline bg-canvas p-2 text-caption">
                <div className="border-b border-hairline px-2 pb-2">
                  <div className="font-medium">{sessionUser.displayName}</div>
                  <div className="mt-0.5 text-micro text-mute">{sessionUser.username} · {sessionUser.role.toUpperCase()}</div>
                </div>
                <div className="flex flex-col py-1">
                  <Link to="/profile" className="px-2 py-1.5 hover:bg-surface-soft">Profile &amp; security</Link>
                  {sessionUser.role === 'admin' && <Link to="/admin/users" className="px-2 py-1.5 hover:bg-surface-soft">Operator accounts</Link>}
                </div>
                <div className="border-t border-hairline pt-1">
                  <Button variant="ghost" onClick={handleLogout} disabled={logout.isPending} className="w-full justify-start px-2 py-1.5 text-caption">
                    {logout.isPending ? 'Logging out…' : 'Log out'}
                  </Button>
                </div>
              </div>
            </details>
          </div>
        )}
        {!sessionUser && authenticationConfigured && (
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1.5 rounded border border-hairline px-2 py-1 text-micro">
              <span className="text-mute">ROLE</span>
              <span className="font-semibold">NOT SIGNED IN</span>
            </span>
            <Link to="/login" className="rounded border border-hairline px-2 py-1 text-micro hover:bg-surface-soft">Sign in</Link>
          </div>
        )}

        <ThemeToggle />
      </div>
    </header>
  )
}
