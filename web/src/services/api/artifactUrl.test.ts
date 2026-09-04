import { afterEach, describe, expect, it, vi } from 'vitest'

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
})

describe('safeArtifactUrl', () => {
  it('allows only configured HTTPS artifact hosts', async () => {
    vi.stubEnv('VITE_SELENE_ARTIFACT_HOSTS', 'artifacts.example.org')
    const { safeArtifactUrl } = await import('./artifactUrl')
    expect(safeArtifactUrl('https://artifacts.example.org/run/output.png')).toBe('https://artifacts.example.org/run/output.png')
    expect(safeArtifactUrl('http://artifacts.example.org/run/output.png')).toBeNull()
    expect(safeArtifactUrl('https://untrusted.example.org/run/output.png')).toBeNull()
  })
})
