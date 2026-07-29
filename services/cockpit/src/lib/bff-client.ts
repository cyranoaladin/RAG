import collectionsData from '@/data/collections.json'
import type { RetrievalResponse, RetrievalResult } from '@/generated/contracts'
import { validateRetrievalResponse } from '@/generated/validators'
import type { RagCollection } from '@/types/ui'

export const BFF_ERROR_CODE = 'BFF_REQUEST_FAILED'
const BFF_TIMEOUT_MS = 8000

function requestOptions(init?: RequestInit): RequestInit {
  return {
    ...init,
    headers: {
      'Content-Type': 'application/json',
    },
    signal: AbortSignal.timeout(BFF_TIMEOUT_MS),
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
export async function getCollections(): Promise<{
  items: RagCollection[]
  live: boolean
}> {
  const live = await getApiHealth()
  return { items: collectionsData as RagCollection[], live }
}

/**
 * Le navigateur transmet uniquement les critères de formulaire au BFF.
 * Le profil canonique et l'identité sont construits côté serveur.
 */
export async function search(
  query: string,
  niveau: string,
  audience: string,
): Promise<{ items: RetrievalResult[]; demo: false }> {
  if (!query.trim()) {
    return { items: [], demo: false }
  }
  const response = await requestRetrieval('/api/search', {
    method: 'POST',
    body: JSON.stringify({ query, top_k: 8, niveau, audience }),
  })
  return { items: response.results ?? [], demo: false }
}
