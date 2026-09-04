export interface ApiErrorBody {
  error?: {
    code?: string
    message?: string
  }
}

/** Error returned by the SELENE persisted-state API. */
export class SeleneApiError extends Error {
  readonly code: string
  readonly status: number

  constructor({ code, message, status }: { code: string; message: string; status: number }) {
    super(message)
    this.name = 'SeleneApiError'
    this.code = code
    this.status = status
  }
}

export type QueryValue = string | number | boolean | null | undefined
export type QueryParams = Record<string, QueryValue | readonly QueryValue[]>

function configuredBaseUrl(): string {
  const configured = import.meta.env.VITE_SELENE_API_BASE_URL?.trim() || '/api/v1'
  return configured.replace(/\/+$/, '')
}

function makeUrl(path: string, query?: QueryParams): string {
  const url = new URL(`${configuredBaseUrl()}/${path.replace(/^\/+/, '')}`, window.location.origin)
  for (const [key, value] of Object.entries(query ?? {})) {
    const values = Array.isArray(value) ? value : [value]
    for (const item of values) {
      if (item !== undefined && item !== null && item !== '') url.searchParams.append(key, String(item))
    }
  }
  return url.toString()
}

async function parseError(response: Response): Promise<SeleneApiError> {
  let payload: ApiErrorBody | undefined
  try {
    payload = (await response.json()) as ApiErrorBody
  } catch {
    // A proxy or an unavailable service can return a non-JSON error page.
  }
  return new SeleneApiError({
    code: payload?.error?.code ?? `HTTP_${response.status}`,
    message: payload?.error?.message ?? (response.statusText || 'The SELENE API request failed.'),
    status: response.status,
  })
}

export interface ApiRequestOptions {
  signal?: AbortSignal
  query?: QueryParams
  headers?: HeadersInit
  /** Stable caller-owned UUID used by every retry of one mutation attempt. */
  idempotencyKey?: string
}

/** Generate a cryptographically random UUID for a new browser mutation attempt. */
export function createIdempotencyKey(): string {
  if (typeof globalThis.crypto?.randomUUID === 'function') return globalThis.crypto.randomUUID()
  if (typeof globalThis.crypto?.getRandomValues !== 'function') {
    throw new Error('A secure UUID source is required for persisted mutations.')
  }
  const bytes = new Uint8Array(16)
  globalThis.crypto.getRandomValues(bytes)
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  return [...bytes].map((byte, index) => `${byte.toString(16).padStart(2, '0')}${[3, 5, 7, 9].includes(index) ? '-' : ''}`).join('')
}

async function request<T>(path: string, init: RequestInit, options: ApiRequestOptions = {}): Promise<T> {
  const response = await fetch(makeUrl(path, options.query), {
    ...init,
    signal: options.signal,
    headers: {
      Accept: 'application/json',
      ...options.headers,
      ...init.headers,
    },
  })
  if (!response.ok) throw await parseError(response)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const seleneApi = {
  get<T>(path: string, options?: ApiRequestOptions) {
    return request<T>(path, { method: 'GET' }, options)
  },
  post<TResponse, TBody>(path: string, body: TBody, options?: ApiRequestOptions) {
    const idempotencyKey = options?.idempotencyKey ?? createIdempotencyKey()
    return request<TResponse>(
      path,
      { method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey }, body: JSON.stringify(body) },
      options,
    )
  },
  patch<TResponse, TBody>(path: string, body: TBody, options?: ApiRequestOptions) {
    const idempotencyKey = options?.idempotencyKey ?? createIdempotencyKey()
    return request<TResponse>(
      path,
      { method: 'PATCH', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey }, body: JSON.stringify(body) },
      options,
    )
  },
}

export function isSeleneApiError(error: unknown): error is SeleneApiError {
  return error instanceof SeleneApiError
}
