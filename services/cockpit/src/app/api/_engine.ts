export interface EngineFetchParams {
  method?: 'GET' | 'POST'
  body?: unknown
  identityToken?: string
}

export interface EngineFetchResult {
  status: number
  payload?: unknown
}

const DEFAULT_ENGINE_URL = 'http://rag-engine:8001'
const ENGINE_TIMEOUT_MS = Number.parseInt(
  process.env.RAG_ENGINE_REQUEST_TIMEOUT_MS ?? '8000',
  10,
) || 8000

function resolveEngineUrl(): string {
  return (process.env.RAG_ENGINE_INTERNAL_URL || DEFAULT_ENGINE_URL).replace(/\/$/, '')
}

function resolveEngineToken(): string {
  const token = (process.env.RAG_ENGINE_INTERNAL_TOKEN || '').trim()
  if (!token) {
    throw new Error('Configuration moteur manquante: RAG_ENGINE_INTERNAL_TOKEN')
  }
  return token
}

export async function fetchEngine(
  endpoint:
    | '/search/v2'
    | '/catalogue/v2'
    | '/collections/v2'
    | '/collections/readiness'
    | '/chat'
    | '/admin/health',
  params: EngineFetchParams = {},
): Promise<EngineFetchResult> {
  const token = resolveEngineToken()
  const headers = new Headers()
  headers.set('Accept', 'application/json')
  headers.set('Content-Type', 'application/json')

  headers.set('Authorization', `Bearer ${token}`)
  if (params.identityToken) {
    headers.set('X-Nexus-Identity', params.identityToken)
  }

  const init: RequestInit = {
    method: params.method ?? 'GET',
    headers,
    signal: AbortSignal.timeout(ENGINE_TIMEOUT_MS),
  }

  if (params.body !== undefined) {
    init.body = JSON.stringify(params.body)
  }

  const target = `${resolveEngineUrl()}${endpoint}`
  const response = await fetch(target, init)
  const status = response.status

  if (!response.ok) {
    const text = await response.text().catch(() => '')
    return {status, payload: text ? {detail: text} : undefined}
  }

  const payload = await response.json()
  return {status, payload}
}

/** Public endpoints are closed unless the engine proves every collection ready. */
export async function isPublicLaunchReady(identityToken: string): Promise<boolean> {
  try {
    const result = await fetchEngine('/collections/readiness', { identityToken })
    if (result.status !== 200 || typeof result.payload !== 'object' || result.payload === null) {
      return false
    }
    return (result.payload as { launch_ready?: unknown }).launch_ready === true
  } catch {
    return false
  }
}
