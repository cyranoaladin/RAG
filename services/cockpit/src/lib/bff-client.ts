import type {
  RetrievalResponse,
  RetrievalResult,
} from '@/generated/contracts'
import type { RagCollection } from '@/types/ui'
import { validateRetrievalResponse, validateSearchPayload } from '@/generated/validators'
import { BFF_BROWSER_TIMEOUT_MS } from '@/lib/request-deadlines'

export const BFF_ERROR_CODE = 'BFF_REQUEST_FAILED'

const DEFAULT_COLLECTIONS_FROM_ROUTE = '/api/collections'

export interface BffCollectionsState {
  items: RagCollection[]
  live: boolean
  launchReady: boolean
  totalCollections: number
  readyCollections: number
  blockers: string[]
}

function requestOptions(init?: RequestInit): RequestInit {
  return {
    ...init,
    headers: {
      'Content-Type': 'application/json',
    },
    signal: AbortSignal.timeout(BFF_BROWSER_TIMEOUT_MS),
  }
}

async function requestRetrieval(
  path: '/api/search',
  init: RequestInit,
): Promise<RetrievalResponse> {
  try {
    const response = await fetch(path, requestOptions(init))
    if (!response.ok) {
      throw new Error(BFF_ERROR_CODE)
    }
    const payload: unknown = await response.json()
    if (!validateRetrievalResponse(payload)) {
      throw new Error(BFF_ERROR_CODE)
    }
    return payload
  } catch {
    throw new Error(BFF_ERROR_CODE)
  }
}

function assertCollectionsPayload(
  payload: unknown,
): payload is BffCollectionsState {
  if (typeof payload !== 'object' || payload === null) {
    return false
  }
  const body = payload as Record<string, unknown>
  return (
    Array.isArray(body.items) &&
    typeof body.live === 'boolean' &&
    typeof body.launchReady === 'boolean' &&
    typeof body.totalCollections === 'number' &&
    typeof body.readyCollections === 'number' &&
    Array.isArray(body.blockers)
  )
}

/** Sonde exclusivement le BFF same-origin, sans faire confiance à son corps. */
export async function getApiHealth(): Promise<boolean> {
  try {
    const response = await fetch('/api/health', requestOptions())
    return response.ok
  } catch {
    return false
  }
}

/** Le catalogue est une donnée de présentation versionnée dans le dépôt. */
export async function getCollections(): Promise<BffCollectionsState> {
  const live = await getApiHealth()
  try {
    const response = await fetch(DEFAULT_COLLECTIONS_FROM_ROUTE, requestOptions())
    if (!response.ok) {
      return {
        items: [],
        live,
        launchReady: false,
        totalCollections: 0,
        readyCollections: 0,
        blockers: ['endpoint collections indisponible'],
      }
    }

    const payload: unknown = await response.json()
    if (assertCollectionsPayload(payload)) {
      return { ...payload, live }
    }

    return {
      items: [],
      live,
      launchReady: false,
      totalCollections: 0,
      readyCollections: 0,
      blockers: ['catalogue BFF invalide'],
    }
  } catch {
    return {
      items: [],
      live,
      launchReady: false,
      totalCollections: 0,
      readyCollections: 0,
      blockers: ['endpoint collections indisponible'],
    }
  }
}

/**
 * Le navigateur transmet uniquement les critères de formulaire au BFF.
 * Le profil canonique et l'identité sont construits côté serveur.
 */
export async function search(
  query: string,
  collections: string[],
  k?: number,
): Promise<{ items: RetrievalResult[]; demo: false }> {
  if (!query.trim()) {
    return { items: [], demo: false }
  }

  const payload = { query, collections, k }
  if (!validateSearchPayload(payload)) {
    throw new Error(BFF_ERROR_CODE)
  }

  const response = await requestRetrieval('/api/search', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return { items: response.results ?? [], demo: false }
}
