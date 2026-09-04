import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  authRepository,
  type CreateUserAccountInput,
  type UpdateUserAccountInput,
  type UserAccount,
} from '@/repositories/authRepository'
import { useRouteSession } from '@/features/auth/useSession'
import { Button } from '@/components/ui/Button'
import { PageHeader } from '@/components/ui/PageHeader'
import { EmptyState } from '@/components/ui/EmptyState'
import { isSeleneApiError } from '@/services/api/client'

type Role = 'analyst' | 'reviewer' | 'admin'

function useUsers() {
  return useQuery({ queryKey: ['auth', 'users'], queryFn: () => authRepository.listUsers() })
}

function useCreateUser() {
  const queryClient = useQueryClient()
  return useMutation({
    // Wrapped (rather than `mutationFn: authRepository.createUser`) because
    // TanStack Query v5 calls `mutationFn(variables, mutationFnContext)` —
    // passing the repository function directly would leak that internal
    // `{ client, meta, mutationKey }` context object into `createUser`'s
    // `options?: ApiRequestOptions` parameter.
    mutationFn: (input: CreateUserAccountInput) => authRepository.createUser(input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['auth', 'users'] }),
  })
}

function useUpdateUser() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: UpdateUserAccountInput }) => authRepository.updateUser(id, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['auth', 'users'] }),
  })
}

type UpdateUserMutation = ReturnType<typeof useUpdateUser>

interface UserRowProps {
  account: UserAccount
  isSelf: boolean
  updateUser: UpdateUserMutation
}

function UserRow({ account, isSelf, updateUser }: UserRowProps) {
  const [draftRole, setDraftRole] = useState<Role>(account.role)

  // ADR-0016 / update_user_account(): the server forbids self-targeted role
  // changes, but deliberately permits an Admin to rotate their own password
  // or active state. This view still disables its own role/active controls to
  // avoid self-administration from the account roster; the server remains the
  // enforcement boundary for role changes.
  const disabledReason = isSelf ? 'You cannot change your own role or active status.' : undefined
  const rowDisabled = Boolean(disabledReason)
  const isRowPending = updateUser.isPending && updateUser.variables?.id === account.id

  function handleSaveRole() {
    if (rowDisabled) return
    updateUser.mutate({ id: account.id, input: { role: draftRole } })
  }

  function handleToggleActive() {
    if (rowDisabled) return
    updateUser.mutate({ id: account.id, input: { isActive: !account.isActive } })
  }

  return (
    <tr className="border-b border-hairline last:border-b-0">
      <td className="px-3 py-2 font-mono">{account.username}</td>
      <td className="px-3 py-2">{account.displayName}</td>
      <td className="px-3 py-2">
        <div className="flex items-center gap-2">
          <select
            aria-label={`Role for ${account.username}`}
            value={draftRole}
            onChange={(event) => setDraftRole(event.target.value as Role)}
            disabled={rowDisabled}
            title={disabledReason}
            className="border border-hairline bg-canvas px-2 py-1 text-caption uppercase focus:outline-none disabled:opacity-50"
          >
            <option value="analyst">ANALYST</option>
            <option value="reviewer">REVIEWER</option>
            <option value="admin">ADMIN</option>
          </select>
          <Button
            type="button"
            variant="secondary"
            disabled={rowDisabled || draftRole === account.role || isRowPending}
            title={disabledReason}
            onClick={handleSaveRole}
          >
            {isRowPending ? 'Saving…' : 'Save'}
          </Button>
        </div>
      </td>
      <td className="px-3 py-2">
        <div className="flex items-center gap-2">
          <span>{account.isActive ? 'YES' : 'NO'}</span>
          <Button
            type="button"
            variant="secondary"
            disabled={rowDisabled || isRowPending}
            title={disabledReason}
            onClick={handleToggleActive}
          >
            {account.isActive ? 'Deactivate' : 'Activate'}
          </Button>
        </div>
      </td>
    </tr>
  )
}

export function UsersRoute() {
  const sessionUser = useRouteSession()
  const usersQuery = useUsers()
  const createUser = useCreateUser()
  const updateUser = useUpdateUser()
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<Role>('analyst')

  if (sessionUser?.role !== 'admin') {
    return (
      <div className="p-6">
        <EmptyState title="FORBIDDEN" description="Admin role is required to manage operator accounts." />
      </div>
    )
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    createUser.mutate(
      { username, displayName, password, role },
      { onSuccess: () => { setUsername(''); setDisplayName(''); setPassword('') } },
    )
  }

  return (
    <div className="flex flex-col gap-6 p-6">
      <PageHeader
        eyebrow="System"
        title="Operator accounts"
        description="Create accounts and assign roles. There is no self-service signup."
        actions={<Link to="/admin" className="text-caption text-accent hover:underline">← Platform status</Link>}
      />

      <section className="border border-hairline">
        <table className="w-full border-collapse text-caption">
          <thead className="bg-surface-soft">
            <tr>
              {['USERNAME', 'DISPLAY NAME', 'ROLE', 'ACTIVE'].map((heading) => (
                <th key={heading} className="border-b border-hairline px-3 py-2 text-left text-micro uppercase tracking-wide text-mute">
                  {heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(usersQuery.data ?? []).map((account) => (
              <UserRow
                key={account.username}
                account={account}
                isSelf={sessionUser?.username === account.username}
                updateUser={updateUser}
              />
            ))}
          </tbody>
        </table>
        {updateUser.error && (
          <p className="px-3 py-2 text-caption text-danger">
            {isSeleneApiError(updateUser.error) ? updateUser.error.message : 'The account could not be updated.'}
          </p>
        )}
      </section>

      <section className="border border-hairline p-4">
        <h2 className="text-section-title">Create account</h2>
        <form onSubmit={handleSubmit} className="mt-3 grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="new-username" className="block text-micro uppercase tracking-wide text-mute">Username</label>
            <input id="new-username" value={username} onChange={(e) => setUsername(e.target.value)} className="mt-1 w-full border border-hairline bg-canvas px-3 py-2 text-caption focus:outline-none" />
          </div>
          <div>
            <label htmlFor="new-display-name" className="block text-micro uppercase tracking-wide text-mute">Display name</label>
            <input id="new-display-name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} className="mt-1 w-full border border-hairline bg-canvas px-3 py-2 text-caption focus:outline-none" />
          </div>
          <div>
            <label htmlFor="new-password" className="block text-micro uppercase tracking-wide text-mute">Password</label>
            <input id="new-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1 w-full border border-hairline bg-canvas px-3 py-2 text-caption focus:outline-none" />
          </div>
          <div>
            <label htmlFor="new-role" className="block text-micro uppercase tracking-wide text-mute">Role</label>
            <select id="new-role" value={role} onChange={(e) => setRole(e.target.value as Role)} className="mt-1 w-full border border-hairline bg-canvas px-3 py-2 text-caption focus:outline-none">
              <option value="analyst">Analyst</option>
              <option value="reviewer">Reviewer</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <div className="sm:col-span-2">
            <Button type="submit" variant="primary" disabled={!username || !displayName || !password || createUser.isPending}>
              {createUser.isPending ? 'Creating…' : 'Create account'}
            </Button>
            {createUser.error && (
              <p className="mt-2 text-caption text-danger">
                {isSeleneApiError(createUser.error) ? createUser.error.message : 'The account could not be created.'}
              </p>
            )}
          </div>
        </form>
      </section>
    </div>
  )
}
