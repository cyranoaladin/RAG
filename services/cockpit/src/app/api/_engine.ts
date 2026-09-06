export interface EngineFetchParams {
  method?: 'GET' | 'POST'
  body?: unknown
  identityToken?: string
  query?: EngineReviewQueueQuery
  signal?: AbortSignal
  timeoutMs?: number
}

export type EngineReviewQueueQuery = {
  collection?: string
  limit?: number
  offset?: number
}

export interface EngineFetchResult {
  status: number
  payload?: unknown
}

const DEFAULT_ENGINE_URL = 'http://rag-engine:8001'
const ENGINE_TIMEOUT_FLOOR_MS = 8000

export function resolveEngineTimeoutMs(rawValue: string | undefined): number {
  const parsed = Number(rawValue)
  return Number.isSafeInteger(parsed) && parsed >= ENGINE_TIMEOUT_FLOOR_MS
    ? parsed
    : ENGINE_TIMEOUT_FLOOR_MS
}

const ENGINE_TIMEOUT_MS = resolveEngineTimeoutMs(
  process.env.RAG_ENGINE_REQUEST_TIMEOUT_MS,
)

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

/**
 * Clé porteuse du client Cockpit, distincte du credential machine.
 *
 * Le moteur exige deux secrets sur ses routes métier : `Authorization`
 * établit que l'appel vient de la façade autorisée, `X-RAG-API-Key` établit
 * ce que CE client a le droit de faire. Les confondre — ou n'en envoyer
 * qu'un — effondrerait les deux portes en une.
 */
function resolveEngineApiKey(): string {
  const key = (process.env.RAG_ENGINE_API_KEY || '').trim()
  if (!key) {
    throw new Error('Configuration moteur manquante: RAG_ENGINE_API_KEY')
  }
  return key
}

export type EngineEndpoint =
  | '/search/v2'
  | '/catalogue/v2'
  | '/collections/v2'
  | '/collections/readiness'
  | '/chat'
  | '/health'
  | '/review/v2/queue'
  | '/review/v2/decide'

type EngineEndpointWithoutQueue = Exclude<EngineEndpoint, '/review/v2/queue'>
type EngineFetchParamsWithoutQuery = Omit<EngineFetchParams, 'query'> & { query?: never }

export function fetchEngine(
  endpoint: '/review/v2/queue',
  params?: EngineFetchParams,
): Promise<EngineFetchResult>
export function fetchEngine(
  endpoint: EngineEndpointWithoutQueue,
  params?: EngineFetchParamsWithoutQuery,
): Promise<EngineFetchResult>
export async function fetchEngine(
  endpoint: EngineEndpoint,
  params: EngineFetchParams = {},
): Promise<EngineFetchResult> {
  const token = resolveEngineToken()
  const apiKey = resolveEngineApiKey()
  const headers = new Headers()
  headers.set('Accept', 'application/json')
  headers.set('Content-Type', 'application/json')

  headers.set('Authorization', `Bearer ${token}`)
  headers.set('X-RAG-API-Key', apiKey)
  if (params.identityToken) {
    headers.set('X-Nexus-Identity', params.identityToken)
  }

  const init: RequestInit = {
    method: params.method ?? 'GET',
    headers,
    signal: AbortSignal.any([
      AbortSignal.timeout(
        params.timeoutMs === undefined
          ? ENGINE_TIMEOUT_MS
          : Math.max(1, Math.min(params.timeoutMs, ENGINE_TIMEOUT_MS)),
      ),
      ...(params.signal === undefined ? [] : [params.signal]),
    ]),
  }

  if (params.body !== undefined) {
    init.body = JSON.stringify(params.body)
  }

  const target = new URL(`${resolveEngineUrl()}${endpoint}`)
  if (endpoint === '/review/v2/queue' && params.query) {
    const { collection, limit, offset } = params.query
    if (collection !== undefined) {
      target.searchParams.set('collection', collection)
    }
    if (limit !== undefined) {
      target.searchParams.set('limit', String(limit))
    }
    if (offset !== undefined) {
      target.searchParams.set('offset', String(offset))
    }
  }

  const response = await fetch(target.toString(), init)
  const status = response.status

  if (!response.ok) {
    const text = await response.text().catch(() => '')
    return {status, payload: text ? {detail: text} : undefined}
  }

  const payload = await response.json()
  return {status, payload}
}

/** Public endpoints are closed unless the engine proves every collection ready. */
export async function isPublicLaunchReady(
  identityToken: string,
  requestBudget: Pick<EngineFetchParams, 'signal' | 'timeoutMs'> = {},
): Promise<boolean> {
  try {
    const result = await fetchEngine('/collections/readiness', {
      identityToken,
      ...requestBudget,
    })
    if (result.status !== 200 || typeof result.payload !== 'object' || result.payload === null) {
      return false
    }
    return (result.payload as { launch_ready?: unknown }).launch_ready === true
  } catch {
    return false
  }
}
