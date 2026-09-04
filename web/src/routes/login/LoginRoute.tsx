import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { isSeleneApiError } from '@/services/api/client'
import { useLogin } from '@/features/auth/useLogin'

export function LoginRoute() {
  const navigate = useNavigate()
  const login = useLogin()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    login.mutate(
      { username, password },
      { onSuccess: () => navigate('/', { replace: true }) },
    )
  }

  return (
    <div className="flex h-screen items-center justify-center bg-canvas p-6">
      <form onSubmit={handleSubmit} className="w-full max-w-sm border border-hairline p-6">
        <h1 className="text-section-title">SELENE-XR</h1>
        <p className="mt-1 text-caption text-mute">Sign in with your operator account.</p>

        <label htmlFor="login-username" className="mt-5 block text-micro uppercase tracking-wide text-mute">
          Username
        </label>
        <input
          id="login-username"
          name="username"
          autoComplete="username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          className="mt-1 w-full border border-hairline bg-canvas px-3 py-2 text-caption focus:outline-none"
        />

        <label htmlFor="login-password" className="mt-4 block text-micro uppercase tracking-wide text-mute">
          Password
        </label>
        <input
          id="login-password"
          name="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="mt-1 w-full border border-hairline bg-canvas px-3 py-2 text-caption focus:outline-none"
        />

        <Button
          type="submit"
          variant="primary"
          disabled={!username || !password || login.isPending}
          className="mt-5 w-full justify-center"
        >
          {login.isPending ? 'Signing in…' : 'Log in'}
        </Button>

        {login.error && (
          <p className="mt-3 text-caption text-danger">
            {isSeleneApiError(login.error) ? login.error.message : 'The login request failed.'}
          </p>
        )}
      </form>
    </div>
  )
}
