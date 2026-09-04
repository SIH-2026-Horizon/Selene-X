import { seleneApi, type ApiRequestOptions } from '@/services/api/client'
import type { ApiProfileUpdate, ApiSessionUser, ApiUserAccount, ApiUserAccountPage } from '@/services/api/contracts'

export interface SessionUser {
  username: string
  displayName: string
  role: 'analyst' | 'reviewer' | 'admin'
}

export interface UserAccount {
  /** The account's server-side UUID — the `{id}` path parameter for `PATCH /api/v1/auth/users/{id}`. */
  id: string
  username: string
  displayName: string
  role: 'analyst' | 'reviewer' | 'admin'
  isActive: boolean
}

export interface CreateUserAccountInput {
  username: string
  password: string
  role: 'analyst' | 'reviewer' | 'admin'
  displayName: string
}

export interface UpdateUserAccountInput {
  role?: 'analyst' | 'reviewer' | 'admin'
  isActive?: boolean
  newPassword?: string
}

export interface UpdateProfileInput {
  displayName?: string
  currentPassword?: string
  newPassword?: string
}

function sessionUserFromApi(user: ApiSessionUser): SessionUser {
  return { username: user.username, displayName: user.display_name, role: user.role }
}

function userAccountFromApi(account: ApiUserAccount): UserAccount {
  return {
    id: account.id,
    username: account.username,
    displayName: account.display_name,
    role: account.role,
    isActive: account.is_active,
  }
}

export const authRepository = {
  async login(username: string, password: string, options?: ApiRequestOptions): Promise<SessionUser> {
    return sessionUserFromApi(
      await seleneApi.post<ApiSessionUser, { username: string; password: string }>(
        'auth/login',
        { username, password },
        options,
      ),
    )
  },

  async logout(options?: ApiRequestOptions): Promise<void> {
    await seleneApi.post<void, Record<string, never>>('auth/logout', {}, options)
  },

  async getSession(options?: ApiRequestOptions): Promise<SessionUser> {
    return sessionUserFromApi(await seleneApi.get<ApiSessionUser>('auth/session', options))
  },

  async updateProfile(input: UpdateProfileInput, options?: ApiRequestOptions): Promise<SessionUser> {
    const body: ApiProfileUpdate = {}
    if (input.displayName !== undefined) body.display_name = input.displayName
    if (input.currentPassword !== undefined) body.current_password = input.currentPassword
    if (input.newPassword !== undefined) body.new_password = input.newPassword
    return sessionUserFromApi(await seleneApi.patch<ApiSessionUser, ApiProfileUpdate>('auth/profile', body, options))
  },

  async listUsers(options?: ApiRequestOptions): Promise<UserAccount[]> {
    const page = await seleneApi.get<ApiUserAccountPage>('auth/users', options)
    return page.items.map(userAccountFromApi)
  },

  async createUser(input: CreateUserAccountInput, options?: ApiRequestOptions): Promise<UserAccount> {
    return userAccountFromApi(
      await seleneApi.post<ApiUserAccount, { username: string; password: string; role: string; display_name: string }>(
        'auth/users',
        { username: input.username, password: input.password, role: input.role, display_name: input.displayName },
        options,
      ),
    )
  },

  async updateUser(
    id: string,
    input: UpdateUserAccountInput,
    options?: ApiRequestOptions,
  ): Promise<UserAccount> {
    const body: { role?: string; is_active?: boolean; new_password?: string } = {}
    if (input.role !== undefined) body.role = input.role
    if (input.isActive !== undefined) body.is_active = input.isActive
    if (input.newPassword !== undefined) body.new_password = input.newPassword
    return userAccountFromApi(
      await seleneApi.patch<ApiUserAccount, typeof body>(`auth/users/${encodeURIComponent(id)}`, body, options),
    )
  },
}
