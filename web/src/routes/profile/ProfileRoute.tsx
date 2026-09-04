import { useEffect, useState } from 'react'
import { Navigate } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { ErrorState } from '@/components/ui/ErrorState'
import { PageHeader } from '@/components/ui/PageHeader'
import { useRouteSession } from '@/features/auth/useSession'
import { useUpdateProfile } from '@/features/auth/useUpdateProfile'
import { isSeleneApiError } from '@/services/api/client'

export function ProfileRoute() {
  const sessionUser = useRouteSession()
  const updateProfile = useUpdateProfile()
  const [displayName, setDisplayName] = useState(sessionUser?.displayName ?? '')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')

  useEffect(() => setDisplayName(sessionUser?.displayName ?? ''), [sessionUser?.displayName])

  if (!sessionUser) return <Navigate to="/login" replace />

  const displayNameChanged = displayName.trim() !== sessionUser.displayName
  const changingPassword = Boolean(currentPassword || newPassword)
  const canSave = (displayNameChanged || changingPassword) && (!changingPassword || Boolean(currentPassword && newPassword))

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!canSave) return
    updateProfile.mutate(
      {
        ...(displayNameChanged ? { displayName: displayName.trim() } : {}),
        ...(changingPassword ? { currentPassword, newPassword } : {}),
      },
      { onSuccess: () => { setCurrentPassword(''); setNewPassword('') } },
    )
  }

  return (
    <div className="flex max-w-3xl flex-col gap-6 p-6">
      <PageHeader
        eyebrow="Operator"
        title="Profile & security"
        description="Your role is assigned by an administrator and cannot be changed from this profile."
      />

      <section className="border border-hairline p-4">
        <dl className="grid gap-4 text-caption sm:grid-cols-3">
          <div><dt className="text-micro uppercase tracking-wide text-mute">Username</dt><dd className="mt-1 font-medium">{sessionUser.username}</dd></div>
          <div><dt className="text-micro uppercase tracking-wide text-mute">Assigned role</dt><dd className="mt-1 font-medium">{sessionUser.role.toUpperCase()}</dd></div>
          <div><dt className="text-micro uppercase tracking-wide text-mute">Authority</dt><dd className="mt-1 text-mute">Server-managed</dd></div>
        </dl>
      </section>

      <form onSubmit={handleSubmit} className="border border-hairline p-4">
        <h2 className="text-section-title">Profile settings</h2>
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label htmlFor="profile-display-name" className="block text-micro uppercase tracking-wide text-mute">Display name</label>
            <input id="profile-display-name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} className="mt-1 w-full border border-hairline bg-canvas px-3 py-2 text-caption focus:outline-none" />
          </div>
          <div>
            <label htmlFor="profile-current-password" className="block text-micro uppercase tracking-wide text-mute">Current password</label>
            <input id="profile-current-password" type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} className="mt-1 w-full border border-hairline bg-canvas px-3 py-2 text-caption focus:outline-none" />
          </div>
          <div>
            <label htmlFor="profile-new-password" className="block text-micro uppercase tracking-wide text-mute">New password</label>
            <input id="profile-new-password" type="password" autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} className="mt-1 w-full border border-hairline bg-canvas px-3 py-2 text-caption focus:outline-none" />
          </div>
        </div>
        <p className="mt-3 text-micro text-mute">Password changes require the current password. New passwords must have at least 8 characters.</p>
        <Button type="submit" variant="primary" disabled={!canSave || updateProfile.isPending} className="mt-4">
          {updateProfile.isPending ? 'Saving…' : 'Save profile'}
        </Button>
        {updateProfile.error && <div className="mt-4"><ErrorState code={isSeleneApiError(updateProfile.error) ? updateProfile.error.code : 'PROFILE_UPDATE_FAILED'} message={isSeleneApiError(updateProfile.error) ? updateProfile.error.message : 'The profile could not be updated.'} /></div>}
      </form>
    </div>
  )
}
