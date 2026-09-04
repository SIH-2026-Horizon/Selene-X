const configuredHosts = new Set(
  (import.meta.env.VITE_SELENE_ARTIFACT_HOSTS ?? '')
    .split(',')
    .map((host) => host.trim().toLocaleLowerCase())
    .filter(Boolean),
)

/** Return an artifact URL only when the deployment explicitly trusts its host. */
export function safeArtifactUrl(value: string): string | null {
  try {
    const url = new URL(value)
    if (url.protocol !== 'https:' || !configuredHosts.has(url.hostname.toLocaleLowerCase())) return null
    return url.toString()
  } catch {
    return null
  }
}
