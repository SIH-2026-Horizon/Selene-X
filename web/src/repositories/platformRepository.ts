import type { ApiErrorBody } from '@/services/api/client'

export interface PlatformProbe {
  endpoint: '/healthz' | '/readyz' | '/api/v1/version'
  status: number | null
  ok: boolean
  message: string
}

export interface ServiceVersion {
  service: string
  version: string
  environment: string
}

export interface PlatformStatus {
  liveness: PlatformProbe
  readiness: PlatformProbe
  version: PlatformProbe
  serviceVersion: ServiceVersion | null
}

async function readBody(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    return null
  }
}

function errorMessage(body: unknown, fallback: string): string {
  const error = (body as ApiErrorBody | null)?.error
  return error?.message ?? fallback
}

async function probe(endpoint: PlatformProbe['endpoint'], signal?: AbortSignal): Promise<{ probe: PlatformProbe; body: unknown }> {
  try {
    const response = await fetch(endpoint, { headers: { Accept: 'application/json' }, signal })
    const body = await readBody(response)
    return {
      probe: {
        endpoint,
        status: response.status,
        ok: response.ok,
        message: response.ok ? 'Available' : errorMessage(body, response.statusText || 'Request failed.'),
      },
      body,
    }
  } catch {
    return {
      probe: { endpoint, status: null, ok: false, message: 'The same-origin service could not be reached.' },
      body: null,
    }
  }
}

function isServiceVersion(value: unknown): value is ServiceVersion {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Record<string, unknown>
  return typeof candidate.service === 'string'
    && typeof candidate.version === 'string'
    && typeof candidate.environment === 'string'
}

export const platformRepository = {
  async getStatus(signal?: AbortSignal): Promise<PlatformStatus> {
    const [liveness, readiness, version] = await Promise.all([
      probe('/healthz', signal),
      probe('/readyz', signal),
      probe('/api/v1/version', signal),
    ])
    return {
      liveness: liveness.probe,
      readiness: readiness.probe,
      version: version.probe,
      serviceVersion: version.probe.ok && isServiceVersion(version.body) ? version.body : null,
    }
  },
}
